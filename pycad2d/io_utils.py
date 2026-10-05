# SPDX-License-Identifier: GPL-3.0-only
"""檔案讀寫：.pycad 專案、DXF 匯入（R12 ~ 2018）、DXF 匯出、透過 ODA File Converter 讀寫 DWG。"""
import glob
import base64
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from . import geometry as G
from . import edit_ops as E
from .model import (Document, Layer, Block, Line, Circle, Arc, Polyline, Ellipse, Spline, Point, Text, MText, Hatch,
                    XLine, Dim, Insert, Array, Solid3D, BYLAYER, TWO_PI, LW_BYLAYER)

CJK_FONT = "msjh.ttc"


# ================================================================ .pycad
def save_project(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc.to_json(), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_project(path):
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return Document.from_json(d)


# ================================================================ DXF 匯入
_CODEPAGES = {"ANSI_950": "cp950", "ANSI_936": "gbk", "ANSI_932": "cp932", "ANSI_949": "cp949",
              "ANSI_1250": "cp1250", "ANSI_1251": "cp1251", "ANSI_1252": "cp1252", "ANSI_1253": "cp1253",
              "ANSI_1254": "cp1254", "ANSI_1255": "cp1255", "ANSI_1256": "cp1256", "ANSI_1257": "cp1257",
              "ANSI_1258": "cp1258", "ANSI_874": "cp874", "BIG5": "cp950", "GB2312": "gbk"}


def _decode(raw):
    if raw[:18] == b"AutoCAD Binary DXF":
        raise ValueError("這是二進位 DXF，目前只支援文字 (ASCII) DXF。請在 CAD 中另存成一般 DXF。")
    head = raw[:20000].decode("latin-1")
    ver = re.search(r"\$ACADVER\s*\r?\n\s*1\s*\r?\n\s*(AC\d+)", head)
    cp = re.search(r"\$DWGCODEPAGE\s*\r?\n\s*3\s*\r?\n\s*(\S+)", head)
    if ver and ver.group(1) >= "AC1021":
        return raw.decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    enc = _CODEPAGES.get(cp.group(1).upper(), "cp950") if cp else "cp950"
    try:
        return raw.decode(enc)
    except (UnicodeDecodeError, LookupError):
        return raw.decode("cp950", errors="replace")


def _pairs(text):
    lines = text.splitlines()
    out = []
    i, n = 0, len(lines) - 1
    while i < n:
        try:
            code = int(lines[i].strip())
        except ValueError:
            i += 1
            continue
        out.append((code, lines[i + 1].strip() if code not in (1, 3) else lines[i + 1].rstrip("\r\n")))
        i += 2
    return out


_uni = re.compile(r"\\U\+([0-9A-Fa-f]{4})")


def _txt(s):
    s = _uni.sub(lambda m: chr(int(m.group(1), 16)), s)
    for a, b in (("%%c", "Ø"), ("%%C", "Ø"), ("%%d", "°"), ("%%D", "°"), ("%%p", "±"), ("%%P", "±"),
                 ("%%u", ""), ("%%U", ""), ("%%o", ""), ("%%O", ""), ("%%%", "%")):
        s = s.replace(a, b)
    return s


def _mtext_clean(s):
    s = _txt(s)
    s = s.replace("\\\\", "\x00").replace("\\{", "\x01").replace("\\}", "\x02")
    s = re.sub(r"\\[Pp]", "\n", s)
    s = s.replace("\\~", " ").replace("^J", "\n").replace("^I", " ")
    s = re.sub(r"\\S([^;]*?)[\^#/]([^;]*?);", r"\1/\2", s)
    s = re.sub(r"\\[ACcFfHhQTWp][^;\\]*;", "", s)
    s = re.sub(r"\\[LlOoKkNX]", "", s)
    s = s.replace("{", "").replace("}", "")
    return s.replace("\x00", "\\").replace("\x01", "{").replace("\x02", "}")


class _Rec:
    """一筆 DXF 記錄（一個 0 群碼開頭的物件）。"""
    __slots__ = ("type", "data")

    def __init__(self, typ, data):
        self.type, self.data = typ, data

    def f(self, code, default=0.0):
        for c, v in self.data:
            if c == code:
                try:
                    return float(v)
                except ValueError:
                    return default
        return default

    def i(self, code, default=0):
        return int(self.f(code, default))

    def s(self, code, default=""):
        for c, v in self.data:
            if c == code:
                return v
        return default

    def has(self, code):
        return any(c == code for c, _ in self.data)

    def all(self, code):
        out = []
        for c, v in self.data:
            if c == code:
                try:
                    out.append(float(v))
                except ValueError:
                    out.append(0.0)
        return out


def _records(pairs):
    out, cur = [], None
    for c, v in pairs:
        if c == 0:
            cur = _Rec(v.upper(), [])
            out.append(cur)
        elif cur is not None:
            cur.data.append((c, v))
    return out


def _common(r):
    lt = r.s(6, "ByLayer")
    if lt.upper() == "BYLAYER":
        lt = "ByLayer"
    elif lt.upper() == "BYBLOCK":
        lt = "ByBlock"
    elif lt.upper() == "CONTINUOUS":
        lt = "Continuous"
    tc = r.i(420, -1) if r.has(420) else -1
    return dict(layer=_txt(r.s(8, "0")) or "0", color=abs(r.i(62, BYLAYER)), truecolor=tc,
                ltype=lt, lw=r.i(370, LW_BYLAYER), lts=r.f(48, 1.0) or 1.0)


def _hatch_loops(data):
    """依序解析 HATCH 的邊界路徑。"""
    n = len(data)
    i = 0
    while i < n and data[i][0] != 91:
        i += 1
    if i >= n:
        return []
    nloops = int(float(data[i][1]))
    i += 1
    loops, prim_loops = [], []
    fl = lambda v: float(v)
    for _ in range(nloops):
        while i < n and data[i][0] != 92:
            i += 1
        if i >= n:
            break
        flag = int(float(data[i][1]))
        i += 1
        prims = []
        if flag & 2:
            closed, nv = True, 0
            while i < n and data[i][0] in (72, 73, 93):
                if data[i][0] == 73:
                    closed = bool(int(float(data[i][1])))
                elif data[i][0] == 93:
                    nv = int(float(data[i][1]))
                i += 1
            pts = []
            for _v in range(nv):
                if i + 1 >= n or data[i][0] != 10:
                    break
                x, y = fl(data[i][1]), fl(data[i + 1][1])
                i += 2
                b = 0.0
                if i < n and data[i][0] == 42:
                    b = fl(data[i][1])
                    i += 1
                pts.append((x, y, b))
            prims = G.poly_prims(pts, True)
        else:
            ne = 0
            if i < n and data[i][0] == 93:
                ne = int(float(data[i][1]))
                i += 1
            for _e in range(ne):
                if i >= n or data[i][0] != 72:
                    break
                et = int(float(data[i][1]))
                i += 1
                ed = []
                while i < n and data[i][0] not in (72, 97, 92):
                    ed.append(data[i])
                    i += 1
                g = _Rec("EDGE", ed)
                if et == 1:
                    prims.append(('L', g.f(10), g.f(20), g.f(11), g.f(21)))
                elif et == 2:
                    ccw = bool(g.i(73, 1))
                    a0, a1 = (g.f(50), g.f(51)) if ccw else (360.0 - g.f(51), 360.0 - g.f(50))
                    span = (a1 - a0) % 360.0 or 360.0
                    prims.append(('A', g.f(10), g.f(20), g.f(40), a0 % 360.0, span, ccw))
                elif et == 3:
                    ccw = bool(g.i(73, 1))
                    a0, a1 = (g.f(50), g.f(51)) if ccw else (360.0 - g.f(51), 360.0 - g.f(50))
                    pts = G.ellipse_points(g.f(10), g.f(20), g.f(11), g.f(21), g.f(40, 1.0),
                                           math.radians(a0), math.radians(a1))
                    if not ccw:
                        pts.reverse()
                    for k in range(len(pts) - 1):
                        prims.append(('L', pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1]))
                elif et == 4:
                    xs, ys = g.all(10), g.all(20)
                    ctrl = list(zip(xs, ys))
                    nk = g.i(95, 0)
                    knots = g.all(40)[:nk]
                    pts = G.bspline_points(ctrl, knots, g.i(94, 3)) if len(ctrl) >= 2 else \
                        list(zip(g.all(11), g.all(21)))
                    for k in range(len(pts) - 1):
                        prims.append(('L', pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1]))
        if i < n and data[i][0] == 97:
            cnt = int(float(data[i][1]))
            i += 1
            while cnt > 0 and i < n and data[i][0] == 330:
                i += 1
                cnt -= 1
        pts = G.flatten_prims(prims, 6.0)
        if len(pts) > 1 and G.dist(pts[0], pts[-1]) < 1e-9:
            pts = pts[:-1]
        if len(pts) >= 3:
            loops.append(pts)
            prim_loops.append([tuple(pr) for pr in prims])
    return loops, prim_loops


def _convert(recs, doc, skipped):
    """把一串 DXF 記錄轉成圖元清單。"""
    out = []
    i, n = 0, len(recs)
    while i < n:
        r = recs[i]
        i += 1
        t = r.type
        if r.i(67, 0) == 1 or r.i(60, 0) == 1:
            if t == "POLYLINE" or (t == "INSERT" and r.i(66, 0)):
                while i < n and recs[i].type != "SEQEND":
                    i += 1
            continue
        kw = _common(r)
        flip = r.f(230, 1.0) < 0
        sx = -1.0 if flip else 1.0
        try:
            if t == "LINE":
                out.append(Line(x1=r.f(10), y1=r.f(20), x2=r.f(11), y2=r.f(21), **kw))
            elif t == "CIRCLE":
                if r.f(40) > 0:
                    out.append(Circle(cx=r.f(10) * sx, cy=r.f(20), r=r.f(40), **kw))
            elif t == "ARC":
                if r.f(40) > 0:
                    a0, a1 = r.f(50), r.f(51)
                    if flip:
                        a0, a1 = 180.0 - a1, 180.0 - a0
                    out.append(Arc(cx=r.f(10) * sx, cy=r.f(20), r=r.f(40), a0=a0 % 360.0, a1=a1 % 360.0, **kw))
            elif t == "LWPOLYLINE":
                pts, widths = [], []
                for c, v in r.data:
                    if c == 10:
                        pts.append([float(v) * sx, 0.0, 0.0]); widths.append([0.0, 0.0])
                    elif c == 20 and pts:
                        pts[-1][1] = float(v)
                    elif c == 40 and widths:
                        widths[-1][0] = abs(float(v))
                    elif c == 41 and widths:
                        widths[-1][1] = abs(float(v))
                    elif c == 42 and pts:
                        pts[-1][2] = float(v) * sx
                if len(pts) >= 2:
                    out.append(Polyline(pts=[tuple(p) for p in pts], closed=bool(r.i(70) & 1),
                                        const_width=abs(r.f(43, 0.0)), widths=[tuple(w) for w in widths], **kw))
            elif t == "POLYLINE":
                flags = r.i(70)
                pts, widths = [], []
                while i < n and recs[i].type == "VERTEX":
                    v = recs[i]
                    i += 1
                    if v.i(70) & 16 or v.i(70) & 128 and not v.i(70) & 64:
                        continue
                    pts.append((v.f(10), v.f(20), v.f(42)))
                    widths.append((abs(v.f(40, 0.0)), abs(v.f(41, 0.0))))
                if i < n and recs[i].type == "SEQEND":
                    i += 1
                if flags & (16 | 64):
                    skipped["POLYLINE(網面)"] += 1
                elif len(pts) >= 2:
                    out.append(Polyline(pts=pts, closed=bool(flags & 1), widths=widths, **kw))
            elif t == "ELLIPSE":
                t0, t1 = r.f(41, 0.0), r.f(42, TWO_PI)
                out.append(Ellipse(cx=r.f(10), cy=r.f(20), mx=r.f(11), my=r.f(21), ratio=r.f(40, 1.0) or 1.0,
                                   t0=t0, t1=t1, **kw))
                if flip:
                    out[-1] = out[-1].clone(ratio=out[-1].ratio)
            elif t == "SPLINE":
                ctrl = list(zip(r.all(10), r.all(20)))
                fit = list(zip(r.all(11), r.all(21)))
                if len(ctrl) >= 2:
                    out.append(Spline(ctrl=ctrl, knots=r.all(40), degree=r.i(71, 3) or 3, closed=bool(r.i(70) & 1),
                                      **kw))
                elif len(fit) >= 2:
                    out.append(Spline(fit=fit, closed=bool(r.i(70) & 1), **kw))
            elif t == "POINT":
                out.append(Point(x=r.f(10), y=r.f(20), **kw))
            elif t in ("TEXT", "ATTRIB"):
                s = _txt(r.s(1, ""))
                if s.strip():
                    ha, va = r.i(72), r.i(74 if t == "ATTRIB" else 73)
                    x, y = r.f(10), r.f(20)
                    if (ha or va) and r.has(11) and ha not in (3, 5):
                        x, y = r.f(11), r.f(21)
                    if ha == 4:
                        ha, va = 1, 2
                    elif ha in (3, 5):
                        ha = 0
                    out.append(Text(x=x, y=y, text=s, height=abs(r.f(40, 2.5)) or 2.5, rot=r.f(50) % 360.0,
                                    halign=ha if ha in (0, 1, 2) else 0, valign=va if va in (0, 1, 2, 3) else 0, **kw))
            elif t == "MTEXT":
                s = _mtext_clean("".join(v for c, v in r.data if c == 3) + r.s(1, ""))
                if s.strip():
                    rot = r.f(50)
                    if r.has(11):
                        rot = math.degrees(math.atan2(r.f(21), r.f(11)))
                    out.append(MText(x=r.f(10), y=r.f(20), text=s, height=abs(r.f(40, 2.5)) or 2.5, rot=rot % 360.0,
                                     width=max(0.0, r.f(41)), attach=min(9, max(1, r.i(71, 1))), **kw))
            elif t == "INSERT":
                name = _txt(r.s(2))
                nc, nr = max(1, r.i(70, 1)), max(1, r.i(71, 1))
                rot = r.f(50)
                base_ins=Insert(name=name, x=r.f(10), y=r.f(20), sx=r.f(41, 1.0) or 1.0,
                                sy=r.f(42, 1.0) or 1.0, rot=rot % 360.0, **kw)
                if nc>1 or nr>1:
                    # DXF MINSERT (INSERT with row/column counts) is a single array-like
                    # object. Preserve that relationship instead of exploding it on import.
                    cv=G.m_vec(G.m_rotate((0,0),rot),(r.f(44),0.0))
                    rv=G.m_vec(G.m_rotate((0,0),rot),(0.0,r.f(45)))
                    out.append(Array(source=[base_ins], mode="RECT", rows=nr, cols=nc,
                                     dx=abs(r.f(44)), dy=abs(r.f(45)), col_vec=cv, row_vec=rv, **kw))
                else:
                    out.append(base_ins)
                if r.i(66, 0):
                    sub = []
                    while i < n and recs[i].type != "SEQEND":
                        sub.append(recs[i])
                        i += 1
                    i += 1
                    out += _convert(sub, doc, skipped)
            elif t == "DIMENSION":
                # Reconstruct editable PyCAD dimensions instead of importing the
                # anonymous *D... graphics block as a dead INSERT.  DXF group 70's
                # low three bits carry the dimension type.
                dt=r.i(70,0)&7; text=_txt(r.s(1,""))
                if text in ("<>"," "):text=""
                p10=(r.f(10),r.f(20));p11=(r.f(11),r.f(21));p13=(r.f(13),r.f(23));p14=(r.f(14),r.f(24));p15=(r.f(15),r.f(25))
                de=None
                try:
                    if dt==0 and r.has(13) and r.has(14):
                        de=Dim(kind="LIN",pts=[p13,p14,p10],text=text,rot=r.f(50,0.0)%180.0,**kw)
                    elif dt==1 and r.has(13) and r.has(14):
                        de=Dim(kind="ALI",pts=[p13,p14,p10],text=text,**kw)
                    elif dt in (3,4) and r.has(15):
                        # Diameter/radius: center is group 15; group 10 is definition
                        # point on the measured circle and group 11 is text/location.
                        de=Dim(kind="DIA" if dt==3 else "RAD",pts=[p15,p10,p11],text=text,**kw)
                    elif dt==5 and r.has(13) and r.has(14) and r.has(15):
                        de=Dim(kind="ANG",pts=[p15,p13,p14,p10],text=text,**kw)
                except Exception:
                    de=None
                if de is not None:
                    out.append(de)
                else:
                    name=_txt(r.s(2))
                    if name:out.append(Insert(name=name,x=0.0,y=0.0,**kw))
                    else:skipped[t]+=1
            elif t == "HATCH":
                loops, loop_prims = _hatch_loops(r.data)
                if loops:
                    solid = bool(r.i(70, 0))
                    out.append(Hatch(loops=loops, loop_prims=loop_prims,
                                     pattern="SOLID" if solid else (r.s(2, "ANSI31") or "ANSI31").upper(),
                                     scale=r.f(41, 1.0) or 1.0, angle=r.f(52, 0.0), **kw))
                else:
                    skipped[t] += 1
            elif t in ("SOLID", "TRACE"):
                p = [(r.f(10), r.f(20)), (r.f(11), r.f(21)), (r.f(13, r.f(12)), r.f(23, r.f(22))), (r.f(12), r.f(22))]
                lp = [q for k, q in enumerate(p) if k == 0 or G.dist(q, p[k - 1]) > 1e-12]
                if len(lp) >= 3:
                    out.append(Hatch(loops=[lp], pattern="SOLID", **kw))
            elif t == "3DFACE":
                p = [(r.f(10), r.f(20)), (r.f(11), r.f(21)), (r.f(12), r.f(22)), (r.f(13), r.f(23))]
                out.append(Polyline(pts=[q + (0.0,) for q in p], closed=True, **kw))
            elif t == "LEADER":
                pts = list(zip(r.all(10), r.all(20)))
                if len(pts) >= 2:
                    out.append(Polyline(pts=[q + (0.0,) for q in pts], **kw))
                    if r.i(71, 1):
                        s = doc.vars["DIMASZ"] * doc.vars.get("DIMSCALE", 1.0)
                        a = G.ang(pts[0], pts[1])
                        b = G.polar(pts[0], a, s)
                        out.append(Hatch(loops=[[pts[0], G.polar(b, a + 90, s / 6), G.polar(b, a - 90, s / 6)]], **kw))
            elif t in ("XLINE", "RAY"):
                if abs(r.f(11)) + abs(r.f(21)) > 0:
                    out.append(XLine(x=r.f(10), y=r.f(20), dx=r.f(11), dy=r.f(21), ray=(t == "RAY"), **kw))
            elif t in ("SEQEND", "VERTEX", "ATTDEF", "ENDBLK", "BLOCK"):
                pass
            else:
                skipped[t] += 1
        except (ValueError, IndexError, TypeError, ZeroDivisionError):
            skipped[t + "(格式錯誤)"] += 1
    return out


def import_dxf(path):
    """讀取 DXF，回傳 Document。doc.report 內有匯入統計。"""
    with open(path, "rb") as f:
        pairs = _pairs(_decode(f.read()))
    doc = Document()
    skipped = Counter()
    sections = {}
    i, n = 0, len(pairs)
    while i < n:
        if pairs[i] == (0, "SECTION") and i + 1 < n and pairs[i + 1][0] == 2:
            name = pairs[i + 1][1].upper()
            j = i + 2
            while j < n and pairs[j] != (0, "ENDSEC"):
                j += 1
            sections[name] = pairs[i + 2:j]
            i = j
        i += 1
    if not sections and pairs:
        sections["ENTITIES"] = pairs
    # HEADER
    hd = sections.get("HEADER", [])
    hv = {}
    for k, (c, v) in enumerate(hd):
        if c == 9 and k + 1 < len(hd):
            hv[v.upper()] = hd[k + 1][1]
    for var, key in (("LTSCALE", "$LTSCALE"), ("DIMSCALE", "$DIMSCALE"), ("TEXTSIZE", "$TEXTSIZE"),
                     ("DIMTXT", "$DIMTXT"), ("DIMASZ", "$DIMASZ")):
        try:
            v = float(hv.get(key, ""))
            if v > 0:
                doc.vars[var] = v
        except ValueError:
            pass
    try:
        doc.vars["INSUNITS"] = int(float(hv.get("$INSUNITS", doc.vars.get("INSUNITS", 4))))
    except (TypeError, ValueError):
        pass
    # TABLES
    for r in _records(sections.get("TABLES", [])):
        if r.type == "LAYER":
            name = _txt(r.s(2))
            if not name:
                continue
            col, fl = r.i(62, 7), r.i(70, 0)
            lt = r.s(6, "Continuous")
            doc.layers[name] = Layer(name, color=abs(col) or 7, ltype="Continuous" if lt.upper() == "CONTINUOUS" else lt,
                                     lw=r.i(370, -3), on=col >= 0, frozen=bool(fl & 1), locked=bool(fl & 4),
                                     plot=bool(r.i(290, 1)))
        elif r.type == "LTYPE":
            name = r.s(2)
            pat = r.all(49)
            if name and pat and name.upper() not in ("BYLAYER", "BYBLOCK", "CONTINUOUS"):
                if len(pat) % 2:
                    pat.append(-abs(pat[-1]) or -1.0)
                doc.linetypes[name] = pat
    doc.layers.setdefault("0", Layer("0"))
    # BLOCKS
    recs = _records(sections.get("BLOCKS", []))
    k = 0
    while k < len(recs):
        r = recs[k]
        k += 1
        if r.type != "BLOCK":
            continue
        body = []
        while k < len(recs) and recs[k].type != "ENDBLK":
            body.append(recs[k])
            k += 1
        name = _txt(r.s(2))
        if name.upper().startswith(("*MODEL_SPACE", "*PAPER_SPACE", "$MODEL_SPACE", "$PAPER_SPACE")):
            continue
        doc.blocks[name] = Block(name, r.f(10), r.f(20), _convert(body, doc, skipped))
    # ENTITIES
    doc.entities = _convert(_records(sections.get("ENTITIES", [])), doc, skipped)
    for e in doc.entities:
        doc.layer(e.layer)
    cl = _txt(hv.get("$CLAYER", "0"))
    doc.current_layer = cl if cl in doc.layers else "0"
    doc.block_rev += 1
    doc.source = "DXF"
    doc.report = {"count": len(doc.entities), "blocks": len(doc.blocks), "layers": len(doc.layers),
                  "skipped": dict(skipped)}
    return doc


# ================================================================ DXF 匯出（R12，無相依套件）
def _esc(s):
    return "".join(ch if 32 <= ord(ch) < 127 else "\\U+%04X" % ord(ch) for ch in str(s))


def _num(v):
    s = "%.10f" % float(v)
    s = s.rstrip("0")
    return s + "0" if s.endswith(".") else s


class _W:
    def __init__(self):
        self.out = []

    def __call__(self, code, val):
        self.out.append("%3d" % code)
        self.out.append(_num(val) if isinstance(val, float) else str(val))

    def ent(self, typ, e):
        self(0, typ)
        self(8, _esc(e.layer))
        if e.color != BYLAYER:
            self(62, e.color)
        if e.ltype not in ("ByLayer", "BYLAYER", ""):
            self(6, _esc("CONTINUOUS" if e.ltype == "Continuous" else e.ltype.upper() if e.ltype == "ByBlock" else e.ltype))

    def pt(self, x, y, k=0):
        self(10 + k, float(x))
        self(20 + k, float(y))
        self(30 + k, 0.0)


def _write_r12(w, doc, e, ext, arr_names=None):
    if isinstance(e, Array):
        info=(arr_names or {}).get(id(e))
        if info is not None:
            name,theta,lc,rs=info
            w.ent("INSERT",e);w(2,_esc(name));w.pt(0.0,0.0);w(41,1.0);w(42,1.0)
            if abs(theta)>1e-12:w(50,float(theta))
            w(70,max(1,int(e.cols)));w(71,max(1,int(e.rows)));w(44,float(lc));w(45,float(rs))
        else:
            for part in e.parts():_write_r12(w,doc,part,ext,arr_names)
    elif isinstance(e, Line):
        w.ent("LINE", e)
        w.pt(e.x1, e.y1)
        w.pt(e.x2, e.y2, 1)
    elif isinstance(e, Circle):
        w.ent("CIRCLE", e)
        w.pt(e.cx, e.cy)
        w(40, float(e.r))
    elif isinstance(e, Arc):
        w.ent("ARC", e)
        w.pt(e.cx, e.cy)
        w(40, float(e.r))
        w(50, float(e.a0 % 360.0))
        w(51, float(e.a1 % 360.0))
    elif isinstance(e, (Polyline, Ellipse, Spline)):
        if isinstance(e, Polyline):
            pts, closed = e.pts, e.closed
        else:
            pp = e.points()
            closed = len(pp) > 2 and G.dist(pp[0], pp[-1]) < 1e-9
            pts = [(x, y, 0.0) for x, y in (pp[:-1] if closed else pp)]
        w.ent("POLYLINE", e)
        w(66, 1)
        w.pt(0.0, 0.0)
        w(70, 1 if closed else 0)
        for idx, p in enumerate(pts):
            w(0, "VERTEX")
            w(8, _esc(e.layer))
            w.pt(p[0], p[1])
            if isinstance(e, Polyline):
                if abs(float(getattr(e,"const_width",0.0))) > 1e-12:
                    w(40, float(e.const_width)); w(41, float(e.const_width))
                elif idx < len(getattr(e,"widths",[])):
                    sw, ew = e.widths[idx]
                    if abs(sw)>1e-12:w(40,float(sw))
                    if abs(ew)>1e-12:w(41,float(ew))
            if abs(p[2]) > 1e-12:
                w(42, float(p[2]))
        w(0, "SEQEND")
        w(8, _esc(e.layer))
    elif isinstance(e, Point):
        w.ent("POINT", e)
        w.pt(e.x, e.y)
    elif isinstance(e, Text):
        w.ent("TEXT", e)
        w.pt(e.x, e.y)
        w(40, float(e.height))
        w(1, _esc(e.text))
        if e.rot:
            w(50, float(e.rot))
        w(7, "STANDARD")
        if e.halign or e.valign:
            w(72, e.halign)
            w.pt(e.x, e.y, 1)
            if e.valign:
                w(73, e.valign)
    elif isinstance(e, Hatch):
        if e.pattern.upper() == "SOLID" and len(e.loops) == 1 and len(e.loops[0]) in (3, 4):
            lp = e.loops[0]
            q = [lp[0], lp[1], lp[3] if len(lp) == 4 else lp[2], lp[2]]
            w.ent("SOLID", e)
            for k, p in enumerate(q):
                w.pt(p[0], p[1], k)
        else:
            for lp in e.loops:
                _write_r12(w, doc, Polyline(pts=[(p[0], p[1], 0.0) for p in lp], closed=True, **e.common()), ext, arr_names)
    elif isinstance(e, XLine):
        L = math.hypot(e.dx, e.dy) or 1.0
        d = ext * 4.0
        a = (e.x, e.y) if e.ray else (e.x - e.dx / L * d, e.y - e.dy / L * d)
        _write_r12(w, doc, Line(x1=a[0], y1=a[1], x2=e.x + e.dx / L * d, y2=e.y + e.dy / L * d, **e.common()), ext, arr_names)
    elif isinstance(e, (Dim, MText)):
        for part in (e.parts() if isinstance(e, Dim) else E.explode_entity(doc, e)):
            _write_r12(w, doc, part, ext, arr_names)
    elif isinstance(e, Insert):
        if e.name in doc.blocks:
            w.ent("INSERT", e)
            w(2, _esc(_r12_name(e.name)))
            w.pt(e.x, e.y)
            w(41, float(e.sx))
            w(42, float(e.sy))
            w(50, float(e.rot))


def _r12_name(name):
    return name.replace(" ", "_")


def export_dxf_r12(path, doc):
    w = _W()
    b = doc.extents() or (0.0, 0.0, 100.0, 100.0)
    ext = max(b[2] - b[0], b[3] - b[1], 1.0)
    arr_names={}
    arr_defs=[]
    for ai,e in enumerate(doc.entities):
        if not isinstance(e,Array) or e.mode.upper()!="RECT" or not e.source:continue
        cv=e.col_vec if any(abs(float(v))>G.EPS for v in e.col_vec) else (float(e.dx),0.0)
        rv=e.row_vec if any(abs(float(v))>G.EPS for v in e.row_vec) else (0.0,float(e.dy))
        lc,lr=math.hypot(*cv),math.hypot(*rv)
        if lc<=G.EPS or lr<=G.EPS or abs(cv[0]*rv[0]+cv[1]*rv[1])>max(lc*lr*1e-7,1e-8):continue
        th=math.degrees(math.atan2(cv[1],cv[0]));rs=lr if cv[0]*rv[1]-cv[1]*rv[0]>=0 else -lr
        name="PYCAD_A%04d"%(ai+1);arr_names[id(e)]=(name,th,lc,rs);arr_defs.append((name,th,e))
    w(0, "SECTION")
    w(2, "HEADER")
    w(9, "$ACADVER")
    w(1, "AC1009")
    w(9, "$INSUNITS")
    w(70, int(doc.vars.get("INSUNITS", 4)))
    w(9, "$INSBASE")
    w.pt(0.0, 0.0)
    w(9, "$EXTMIN")
    w.pt(b[0], b[1])
    w(9, "$EXTMAX")
    w.pt(b[2], b[3])
    w(9, "$LTSCALE")
    w(40, float(doc.vars.get("LTSCALE", 1.0)))
    w(9, "$CLAYER")
    w(8, _esc(doc.current_layer))
    w(0, "ENDSEC")
    w(0, "SECTION")
    w(2, "TABLES")
    used_lt = {"Continuous"} | {l.ltype for l in doc.layers.values()} | {e.ltype for e in doc.entities}
    lts = [(k, doc.pattern(k)) for k in used_lt if k not in ("ByLayer", "ByBlock", "BYLAYER", "BYBLOCK", "", "Continuous")]
    w(0, "TABLE")
    w(2, "LTYPE")
    w(70, len(lts) + 1)
    w(0, "LTYPE")
    w(2, "CONTINUOUS")
    w(70, 0)
    w(3, "Solid line")
    w(72, 65)
    w(73, 0)
    w(40, 0.0)
    for name, pat in lts:
        w(0, "LTYPE")
        w(2, _esc(name))
        w(70, 0)
        w(3, _esc(name))
        w(72, 65)
        w(73, len(pat))
        w(40, float(sum(abs(x) for x in pat)))
        for x in pat:
            w(49, float(x))
    w(0, "ENDTAB")
    w(0, "TABLE")
    w(2, "LAYER")
    w(70, len(doc.layers))
    for ly in doc.layers.values():
        w(0, "LAYER")
        w(2, _esc(ly.name))
        w(70, (1 if ly.frozen else 0) | (4 if ly.locked else 0))
        w(62, ly.color if ly.on else -ly.color)
        w(6, "CONTINUOUS" if ly.ltype == "Continuous" else _esc(ly.ltype))
    w(0, "ENDTAB")
    w(0, "TABLE")
    w(2, "STYLE")
    w(70, 1)
    w(0, "STYLE")
    w(2, "STANDARD")
    w(70, 0)
    w(40, 0.0)
    w(41, 1.0)
    w(50, 0.0)
    w(71, 0)
    w(42, 2.5)
    w(3, CJK_FONT)
    w(4, "")
    w(0, "ENDTAB")
    w(0, "ENDSEC")
    w(0, "SECTION")
    w(2, "BLOCKS")
    for blk in doc.blocks.values():
        w(0, "BLOCK");w(8,"0");w(2,_esc(_r12_name(blk.name)));w(70,0);w.pt(blk.bx,blk.by);w(3,_esc(_r12_name(blk.name)))
        for e in blk.entities:_write_r12(w,doc,e,ext,arr_names)
        w(0,"ENDBLK");w(8,"0")
    for name,theta,arr in arr_defs:
        w(0,"BLOCK");w(8,"0");w(2,_esc(name));w(70,0);w.pt(0.0,0.0);w(3,_esc(name))
        inv=G.m_rotate((0,0),-theta)
        for src in arr.source:_write_r12(w,doc,src.transformed(inv),ext,arr_names)
        w(0,"ENDBLK");w(8,"0")
    w(0, "ENDSEC")
    w(0, "SECTION")
    w(2, "ENTITIES")
    for e in doc.entities:
        _write_r12(w, doc, e, ext, arr_names)
    w(0, "ENDSEC")
    w(0, "EOF")
    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        f.write("\n".join(w.out) + "\n")


# ================================================================ DXF 匯出（AutoCAD 2010，需要 ezdxf）
def have_ezdxf():
    try:
        import ezdxf  # noqa: F401
        return True
    except Exception:
        return False


def export_dxf_2010(path, doc):
    """用 ezdxf 寫出 AutoCAD 2010 格式：保留真正的橢圓、雲形線、多行文字、填充線與標註物件。"""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment
    d = ezdxf.new("R2010", setup=True)
    d.header["$LTSCALE"] = float(doc.vars.get("LTSCALE", 1.0))
    d.header["$INSUNITS"] = int(doc.vars.get("INSUNITS", 4))
    d.header["$MEASUREMENT"] = 1
    try:
        d.styles.get("Standard").dxf.font = CJK_FONT
    except Exception:
        pass
    for name, pat in doc.linetypes.items():
        if pat and name not in d.linetypes:
            d.linetypes.add(name, pattern=[sum(abs(x) for x in pat)] + list(pat), description=name)
    for ly in doc.layers.values():
        lt = ly.ltype if ly.ltype in d.linetypes else "Continuous"
        if ly.name in d.layers:
            L = d.layers.get(ly.name)
            L.dxf.color, L.dxf.linetype = ly.color, lt
        else:
            L = d.layers.add(ly.name, color=ly.color, linetype=lt)
        if ly.lw >= 0:
            L.dxf.lineweight = ly.lw
        if not ly.on:
            L.off()
        if ly.frozen:
            L.freeze()
        if ly.locked:
            L.lock()
    if doc.current_layer in d.layers:
        d.header["$CLAYER"] = doc.current_layer
    align = {(0, 0): "LEFT", (1, 0): "CENTER", (2, 0): "RIGHT", (0, 1): "BOTTOM_LEFT", (1, 1): "BOTTOM_CENTER",
             (2, 1): "BOTTOM_RIGHT", (0, 2): "MIDDLE_LEFT", (1, 2): "MIDDLE_CENTER", (2, 2): "MIDDLE_RIGHT",
             (0, 3): "TOP_LEFT", (1, 3): "TOP_CENTER", (2, 3): "TOP_RIGHT"}

    def at(e):
        a = {"layer": e.layer, "color": e.color}
        tc=int(getattr(e,"truecolor",-1) or -1)
        if 0 <= tc <= 0xFFFFFF:
            a["true_color"] = tc
        lt = e.ltype
        if lt in ("ByLayer", "BYLAYER", ""):
            a["linetype"] = "BYLAYER"
        elif lt in ("ByBlock", "BYBLOCK"):
            a["linetype"] = "BYBLOCK"
        elif lt in d.linetypes:
            a["linetype"] = lt
        if e.lw != LW_BYLAYER:
            a["lineweight"] = e.lw
        if abs(e.lts - 1.0) > 1e-9:
            a["ltscale"] = e.lts
        return a

    array_seq=[0]

    def add(sp, e):
        if isinstance(e, Array):
            if e.mode.upper()=="RECT" and e.source and e.rows>=1 and e.cols>=1:
                cv=e.col_vec if any(abs(float(v))>G.EPS for v in e.col_vec) else (float(e.dx),0.0)
                rv=e.row_vec if any(abs(float(v))>G.EPS for v in e.row_vec) else (0.0,float(e.dy))
                lc,lr=math.hypot(*cv),math.hypot(*rv)
                if lc>G.EPS and lr>G.EPS and abs(cv[0]*rv[0]+cv[1]*rv[1]) <= max(lc*lr*1e-7,1e-8):
                    # Encode a rectangular associative PyCAD array as one DXF MINSERT
                    # (INSERT row/column counts) instead of thousands of independent
                    # entities.  Rotation/mirror are represented by local block geometry
                    # plus signed row spacing.
                    theta=math.degrees(math.atan2(cv[1],cv[0])); det=cv[0]*rv[1]-cv[1]*rv[0]
                    rs=lr if det>=0 else -lr
                    array_seq[0]+=1; bn="PYCAD_ARRAY_%04d"%array_seq[0]
                    while bn in d.blocks:
                        array_seq[0]+=1; bn="PYCAD_ARRAY_%04d"%array_seq[0]
                    blk=d.blocks.new(name=bn,base_point=(0,0))
                    inv=G.m_rotate((0,0),-theta)
                    for src in e.source:add(blk,src.transformed(inv))
                    aa=at(e);aa.update(rotation=theta,column_count=max(1,int(e.cols)),row_count=max(1,int(e.rows)),
                                       column_spacing=lc,row_spacing=rs)
                    sp.add_blockref(bn,(0,0),dxfattribs=aa)
                    return
            # Polar/non-orthogonal arrays have no faithful MINSERT equivalent; keep
            # geometry correct by expanding them rather than writing a malformed array.
            for part in e.parts():add(sp,part)
            return
        a = at(e)
        if isinstance(e, Line):
            sp.add_line((e.x1, e.y1), (e.x2, e.y2), dxfattribs=a)
        elif isinstance(e, Circle):
            sp.add_circle((e.cx, e.cy), e.r, dxfattribs=a)
        elif isinstance(e, Arc):
            sp.add_arc((e.cx, e.cy), e.r, e.a0 % 360.0, e.a1 % 360.0, dxfattribs=a)
        elif isinstance(e, Polyline):
            ws=list(getattr(e,"widths",[]) or [])
            data=[]
            for i,p0 in enumerate(e.pts):
                sw,ew = ws[i] if i < len(ws) else (0.0,0.0)
                data.append((p0[0],p0[1],float(sw),float(ew),p0[2]))
            pl=sp.add_lwpolyline(data, format="xyseb", close=e.closed, dxfattribs=a)
            if abs(float(getattr(e,"const_width",0.0))) > 1e-12:
                pl.dxf.const_width=float(e.const_width)
        elif isinstance(e, Ellipse):
            sp.add_ellipse((e.cx, e.cy), major_axis=(e.mx, e.my, 0), ratio=max(1e-6, min(1.0, e.ratio)),
                           start_param=0.0 if e.full() else e.t0, end_param=TWO_PI if e.full() else e.t1,
                           dxfattribs=a)
        elif isinstance(e, Spline):
            if e.ctrl:
                s = sp.add_spline(degree=e.degree, dxfattribs=a)
                s.control_points = [(x, y, 0) for x, y in e.ctrl]
                if len(e.knots) == len(e.ctrl) + e.degree + 1:
                    s.knots = e.knots
                else:
                    s = None
                    sp.add_open_spline([(x, y, 0) for x, y in e.ctrl], degree=min(e.degree, len(e.ctrl) - 1),
                                       dxfattribs=a)
            else:
                pts = [(x, y, 0) for x, y in e.fit]
                if e.closed:
                    pts.append(pts[0])
                sp.add_spline(fit_points=pts, dxfattribs=a)
        elif isinstance(e, Point):
            sp.add_point((e.x, e.y), dxfattribs=a)
        elif isinstance(e, Text):
            t = sp.add_text(e.text, height=e.height, rotation=e.rot, dxfattribs=a)
            t.set_placement((e.x, e.y), align=getattr(TextEntityAlignment, align.get((e.halign, e.valign), "LEFT")))
        elif isinstance(e, MText):
            m = sp.add_mtext(e.text.replace("\\", "\\\\").replace("\n", "\\P"), dxfattribs=a)
            m.dxf.insert = (e.x, e.y)
            m.dxf.char_height = e.height
            m.dxf.attachment_point = e.attach
            m.dxf.rotation = e.rot
            if e.width > 0:
                m.dxf.width = e.width
        elif isinstance(e, Hatch):
            h = sp.add_hatch(color=e.color, dxfattribs={k: v for k, v in a.items() if k in ("layer",)})
            if e.pattern.upper() != "SOLID":
                try:
                    h.set_pattern_fill(e.pattern.upper(), color=e.color, scale=e.scale, angle=e.angle)
                except Exception:
                    h.set_pattern_fill("ANSI31", color=e.color, scale=e.scale, angle=e.angle)
            for k, lp in enumerate(e.loops):
                prims = e.loop_prims[k] if k < len(getattr(e, "loop_prims", [])) else None
                if prims:
                    ep = h.paths.add_edge_path(flags=1 if k == 0 else 16)
                    for pr0 in prims:
                        pr=tuple(pr0)
                        if pr[0]=='L':
                            ep.add_line((pr[1],pr[2]),(pr[3],pr[4]))
                        elif pr[0]=='A':
                            ccw=(len(pr)<7 or bool(pr[6])); ep.add_arc((pr[1],pr[2]),float(pr[3]),
                                float(pr[4]),float(pr[4]+pr[5]),ccw=ccw)
                else:
                    h.paths.add_polyline_path([(p[0], p[1]) for p in lp], is_closed=True, flags=1 if k == 0 else 16)
        elif isinstance(e, XLine):
            L = math.hypot(e.dx, e.dy) or 1.0
            (sp.add_ray if e.ray else sp.add_xline)((e.x, e.y), (e.dx / L, e.dy / L, 0), dxfattribs=a)
        elif isinstance(e, Insert):
            if e.name in doc.blocks:
                a.update(xscale=e.sx, yscale=e.sy, rotation=e.rot)
                sp.add_blockref(e.name, (e.x, e.y), dxfattribs=a)
        elif isinstance(e, Dim):
            if not add_dim(sp, e, a):
                for part in e.parts():
                    add(sp, part)

    def add_dim(sp, e, a):
        ov = {"dimtxt": e.th, "dimasz": e.asz, "dimdec": e.dec, "dimexo": e.th * 0.25, "dimexe": e.th * 0.5,
              "dimgap": e.th * 0.25, "dimtad": 1, "dimzin": 8}
        tx = e.text or "<>"
        p = e.pts
        da = {"layer": e.layer, "color": e.color}
        try:
            if e.kind == "LIN":
                sp.add_linear_dim(base=p[2], p1=p[0], p2=p[1], angle=e.rot, text=tx, override=ov, dxfattribs=da).render()
            elif e.kind == "ALI":
                u = G.ang(p[0], p[1])
                dist = G.cross(math.cos(math.radians(u)), math.sin(math.radians(u)), p[2][0] - p[0][0], p[2][1] - p[0][1])
                sp.add_aligned_dim(p1=p[0], p2=p[1], distance=dist, text=tx, override=ov, dxfattribs=da).render()
            elif e.kind == "RAD":
                sp.add_radius_dim(center=p[0], radius=G.dist(p[0], p[1]), location=p[2], text=tx, override=ov,
                                  dxfattribs=da).render()
            elif e.kind == "DIA":
                sp.add_diameter_dim(center=p[0], radius=G.dist(p[0], p[1]), location=p[2], text=tx, override=ov,
                                    dxfattribs=da).render()
            elif e.kind == "ANG":
                sp.add_angular_dim_3p(base=p[3], center=p[0], p1=p[1], p2=p[2], text=tx, override=ov,
                                      dxfattribs=da).render()
            else:
                return False
            return True
        except Exception:
            return False

    # 圖塊要先全部建立（可能互相巢狀），再填內容
    blks = {}
    for blk in doc.blocks.values():
        if blk.name.startswith("*"):
            continue
        if blk.name in d.blocks:
            d.blocks.delete_block(blk.name, safe=False)
        blks[blk.name] = d.blocks.new(name=blk.name, base_point=(blk.bx, blk.by))
    star = {n for n in doc.blocks if n.startswith("*")}
    for name, b in blks.items():
        for e in doc.blocks[name].entities:
            for x in ([e] if not (isinstance(e, Insert) and e.name in star) else doc.expand(e)):
                add(b, x)
    msp = d.modelspace()
    for e in doc.entities:
        if isinstance(e, Insert) and e.name in star:
            for x in doc.expand(e):       # 匯入的標註外觀圖塊（*D…）：展開成圖元
                add(msp, x)
        else:
            add(msp, e)
    d.saveas(path)


def export_dxf(path, doc, prefer_2010=True):
    """回傳實際寫出的格式名稱。"""
    if prefer_2010 and have_ezdxf():
        export_dxf_2010(path, doc)
        return "DXF R2010"
    export_dxf_r12(path, doc)
    return "R12 DXF"


# ================================================================ 3D export (STL / STEP / OBJ)
def _solid3d(doc):
    return [e for e in doc.entities if isinstance(e, Solid3D) and e.vertices and e.faces]


def _to_mm(doc):
    # AutoCAD INSUNITS -> millimetres. STL/OBJ are unitless in practice, but most
    # slicers/CAD importers assume mm; STEP from CadQuery is millimetre based.
    return {0:1.0, 1:25.4, 2:304.8, 3:1609344.0, 4:1.0, 5:10.0, 6:1000.0,
            7:1000000.0, 8:0.0000254, 9:0.0254, 10:914.4, 14:100.0, 15:10000.0}.get(
                int(getattr(doc, "vars", {}).get("INSUNITS", 4)), 1.0)


def _triangles(solid):
    """Fan-triangulate each polygonal face. Current primitive/extrude faces are planar."""
    out = []
    n = len(solid.vertices)
    for face in solid.faces:
        ids = [int(i) for i in face if 0 <= int(i) < n]
        if len(ids) < 3:
            continue
        a = ids[0]
        for k in range(1, len(ids)-1):
            out.append((solid.vertices[a], solid.vertices[ids[k]], solid.vertices[ids[k+1]]))
    return out


def _normal(a, b, c):
    ux,uy,uz=b[0]-a[0],b[1]-a[1],b[2]-a[2]
    vx,vy,vz=c[0]-a[0],c[1]-a[1],c[2]-a[2]
    nx,ny,nz=uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
    L=math.sqrt(nx*nx+ny*ny+nz*nz)
    if L < 1e-15: return (0.0,0.0,0.0)
    return (nx/L,ny/L,nz/L)


def _oriented_triangles(solid):
    """Return consistently oriented triangles. Uses trimesh when available."""
    tris_idx=[]; n=len(solid.vertices)
    for face in solid.faces:
        ids=[int(i) for i in face if 0<=int(i)<n]
        if len(ids)>=3:
            for k in range(1,len(ids)-1):tris_idx.append((ids[0],ids[k],ids[k+1]))
    try:
        import trimesh
        m=trimesh.Trimesh(vertices=solid.vertices,faces=tris_idx,process=True)
        try:m.fix_normals(multibody=True)
        except TypeError:m.fix_normals()
        return [(tuple(m.vertices[a]),tuple(m.vertices[b]),tuple(m.vertices[c])) for a,b,c in m.faces]
    except Exception:
        if not tris_idx:return []
        cx=sum(v[0] for v in solid.vertices)/len(solid.vertices); cy=sum(v[1] for v in solid.vertices)/len(solid.vertices); cz=sum(v[2] for v in solid.vertices)/len(solid.vertices)
        out=[]
        for ia,ib,ic in tris_idx:
            a,b,c=solid.vertices[ia],solid.vertices[ib],solid.vertices[ic]
            nx,ny,nz=_normal(a,b,c); mx=(a[0]+b[0]+c[0])/3-cx; my=(a[1]+b[1]+c[1])/3-cy; mz=(a[2]+b[2]+c[2])/3-cz
            if nx*mx+ny*my+nz*mz<0:b,c=c,b
            out.append((a,b,c))
        return out


def _export_triangles(solid):
    """High-quality export tessellation, independent from viewport/display LOD."""
    if getattr(solid,"brep_b64",""):
        try:
            sh=_cq_shape_from_solid(solid,1.0)
            bb=sh.BoundingBox();diag=max((bb.xlen*bb.xlen+bb.ylen*bb.ylen+bb.zlen*bb.zlen)**0.5,1e-6)
            tol=max(1e-4,min(0.25,diag/1800.0))
            vv,ff=sh.tessellate(tol)
            verts=[tuple(map(float,v[:3])) for v in vv]
            tmp=Solid3D(vertices=verts,faces=[tuple(map(int,f[:3])) for f in ff],edges=[])
            return _oriented_triangles(tmp)
        except Exception:
            pass
    return _oriented_triangles(solid)

def export_stl(path, doc):
    solids = _solid3d(doc)
    if not solids:
        raise ValueError("圖面中沒有可匯出的 3D 實體。請先建立 BOX、CYLINDER、SPHERE、CONE 或 EXTRUDE 物件。")
    # ASCII STL maximises interoperability and has no optional dependency.
    with open(path, "w", encoding="ascii", errors="ignore") as f:
        f.write("solid PyCAD\n")
        scale=_to_mm(doc)
        for solid in solids:
            for a,b,c in _export_triangles(solid):
                a=tuple(float(x)*scale for x in a); b=tuple(float(x)*scale for x in b); c=tuple(float(x)*scale for x in c)
                n=_normal(a,b,c)
                f.write(" facet normal %.9g %.9g %.9g\n" % n)
                f.write("  outer loop\n")
                for v in (a,b,c): f.write("   vertex %.12g %.12g %.12g\n" % tuple(v))
                f.write("  endloop\n endfacet\n")
        f.write("endsolid PyCAD\n")


def export_obj(path, doc):
    solids = _solid3d(doc)
    if not solids:
        raise ValueError("圖面中沒有可匯出的 3D 實體。")
    scale=_to_mm(doc)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# PyCAD OBJ export; coordinates converted to millimetres\n")
        base=1
        for si, solid in enumerate(solids,1):
            f.write("o Solid_%d_%s\n" % (si, solid.shape))
            if getattr(solid,"brep_b64",""):
                tris=_export_triangles(solid); verts=[]; faces=[]; mp={}
                for tri in tris:
                    ids=[]
                    for q in tri:
                        key=tuple(round(float(x),12) for x in q)
                        if key not in mp:mp[key]=len(verts);verts.append(tuple(map(float,q)))
                        ids.append(mp[key])
                    faces.append(ids)
            else:
                verts=list(solid.vertices);faces=[list(face) for face in solid.faces]
            for x,y,z in verts:f.write("v %.12g %.12g %.12g\n"%(x*scale,y*scale,z*scale))
            for face in faces:
                ids=[int(i) for i in face if 0<=int(i)<len(verts)]
                if len(ids)>=3:f.write("f "+" ".join(str(base+i) for i in ids)+"\n")
            base += len(verts)


def _shape_to_brep_b64(shape):
    """Serialize an OpenCascade shape so .pycad can retain exact CAD geometry."""
    fd,path=tempfile.mkstemp(suffix=".brep"); os.close(fd)
    try:
        shape.exportBrep(path)
        return base64.b64encode(open(path,"rb").read()).decode("ascii")
    finally:
        try: os.unlink(path)
        except OSError: pass

def _shape_from_brep_b64(data):
    if not data:return None
    try: import cadquery as cq
    except Exception:return None
    fd,path=tempfile.mkstemp(suffix=".brep"); os.close(fd)
    try:
        with open(path,"wb") as f:f.write(base64.b64decode(data.encode("ascii")))
        return cq.Shape.importBrep(path)
    finally:
        try: os.unlink(path)
        except OSError: pass

def _cq_shape_from_solid(solid, scale=1.0):
    try:
        import cadquery as cq
    except Exception as ex:
        raise RuntimeError("STEP 匯出需要 CadQuery。請執行：pip install cadquery") from ex
    exact=_shape_from_brep_b64(getattr(solid,"brep_b64",""))
    if exact is not None:
        if abs(float(scale)-1.0) < 1e-12:
            return exact
        # OCC/CadQuery has no simple uniform shape scale API exposed consistently;
        # use a matrix transform when exporting drawings whose units are not millimetres.
        try:
            m=cq.Matrix([[scale,0,0,0],[0,scale,0,0],[0,0,scale,0],[0,0,0,1]])
            return exact.transformGeometry(m)
        except Exception:
            pass
    faces=[]
    n=len(solid.vertices)
    for face in solid.faces:
        ids=[int(i) for i in face if 0 <= int(i) < n]
        if len(ids)<3: continue
        pts=[cq.Vector(*(float(x)*scale for x in solid.vertices[i])) for i in ids]
        try:
            wire=cq.Wire.makePolygon(pts, close=True)
            faces.append(cq.Face.makeFromWires(wire))
        except Exception:
            # Fallback: triangulate a problematic polygon (e.g. non-convex profile).
            a=ids[0]
            for k in range(1,len(ids)-1):
                tp=[cq.Vector(*(float(x)*scale for x in solid.vertices[i])) for i in (a,ids[k],ids[k+1])]
                faces.append(cq.Face.makeFromWires(cq.Wire.makePolygon(tp, close=True)))
    if not faces:
        raise ValueError("3D 實體沒有可匯出的面。")
    shell=cq.Shell.makeShell(faces)
    try:
        result=cq.Solid.makeSolid(shell)
        if result.isValid():
            return result
    except Exception:
        pass
    return shell


def export_step(path, doc):
    solids=_solid3d(doc)
    if not solids:
        raise ValueError("圖面中沒有可匯出的 3D 實體。")
    try:
        import cadquery as cq
    except Exception as ex:
        raise RuntimeError("STEP 匯出需要 CadQuery。請執行：pip install cadquery") from ex
    scale=_to_mm(doc)
    shapes=[_cq_shape_from_solid(s, scale) for s in solids]
    shape=shapes[0] if len(shapes)==1 else cq.Compound.makeCompound(shapes)
    cq.exporters.export(shape, path, exportType="STEP")



# ================================================================ 3D import/export v0.6.2
def export_ply(path, doc):
    solids=_solid3d(doc)
    if not solids: raise ValueError("圖面中沒有可匯出的 3D 實體。")
    scale=_to_mm(doc); vertices=[]; faces=[]
    for solid in solids:
        base=len(vertices)
        vertices += [(x*scale,y*scale,z*scale) for x,y,z in solid.vertices]
        for f in solid.faces:
            ids=[int(i) for i in f if 0<=int(i)<len(solid.vertices)]
            if len(ids)>=3: faces.append([base+i for i in ids])
    with open(path,'w',encoding='ascii') as f:
        f.write('ply\nformat ascii 1.0\ncomment PyCAD v0.6.9.4\n')
        f.write(f'element vertex {len(vertices)}\nproperty float x\nproperty float y\nproperty float z\n')
        f.write(f'element face {len(faces)}\nproperty list uchar int vertex_indices\nend_header\n')
        for v in vertices:f.write('%.12g %.12g %.12g\n'%v)
        for face in faces:f.write(str(len(face))+' '+' '.join(map(str,face))+'\n')


def export_off(path, doc):
    solids=_solid3d(doc)
    if not solids: raise ValueError("圖面中沒有可匯出的 3D 實體。")
    scale=_to_mm(doc); vertices=[]; faces=[]
    for solid in solids:
        base=len(vertices); vertices += [(x*scale,y*scale,z*scale) for x,y,z in solid.vertices]
        for f0 in solid.faces:
            ids=[int(i) for i in f0 if 0<=int(i)<len(solid.vertices)]
            if len(ids)>=3:faces.append([base+i for i in ids])
    with open(path,'w',encoding='ascii') as f:
        f.write('OFF\n%d %d 0\n'%(len(vertices),len(faces)))
        for v in vertices:f.write('%.12g %.12g %.12g\n'%v)
        for face in faces:f.write(str(len(face))+' '+' '.join(map(str,face))+'\n')


def _trimesh_scene(doc):
    try: import trimesh
    except Exception as ex: raise RuntimeError("此格式需要 trimesh。請執行：pip install trimesh") from ex
    scale=_to_mm(doc); meshes=[]
    for s in _solid3d(doc):
        tris=[]
        for face in s.faces:
            ids=[int(i) for i in face if 0<=int(i)<len(s.vertices)]
            if len(ids)>=3:
                for k in range(1,len(ids)-1):tris.append((ids[0],ids[k],ids[k+1]))
        if tris:
            meshes.append(trimesh.Trimesh(vertices=[(x*scale,y*scale,z*scale) for x,y,z in s.vertices],faces=tris,process=False))
    if not meshes: raise ValueError("圖面中沒有可匯出的 3D 實體。")
    return trimesh.Scene(meshes)


def export_3mf(path, doc):
    scene=_trimesh_scene(doc)
    try: data=scene.export(file_type='3mf')
    except Exception as ex: raise RuntimeError("3MF 匯出需要 trimesh 的 3MF 支援。") from ex
    mode='wb' if isinstance(data,(bytes,bytearray)) else 'w'
    with open(path,mode) as f:f.write(data)


def export_gltf(path, doc):
    scene=_trimesh_scene(doc)
    ext=os.path.splitext(path)[1].lower()
    kind='glb' if ext=='.glb' else 'gltf'
    try:data=scene.export(file_type=kind)
    except Exception as ex: raise RuntimeError("glTF/GLB 匯出需要 trimesh。") from ex
    if isinstance(data,dict):
        # glTF may return multiple files; write main JSON and companions beside it.
        root=os.path.dirname(path) or '.'
        main=None
        for name,blob in data.items():
            out=os.path.join(root,name)
            with open(out,'wb' if isinstance(blob,(bytes,bytearray)) else 'w') as f:f.write(blob)
            if name.lower().endswith('.gltf'):main=out
        if main and os.path.abspath(main)!=os.path.abspath(path):shutil.copy(main,path)
    else:
        with open(path,'wb' if isinstance(data,(bytes,bytearray)) else 'w') as f:f.write(data)


def _finite_vertex(v):
    try:
        x,y,z=float(v[0]),float(v[1]),float(v[2])
    except (TypeError,ValueError,IndexError):
        return None
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        return None
    if max(abs(x),abs(y),abs(z)) > 1e12:
        return None
    return (x,y,z)


def _sanitize_mesh(vertices, faces, fix_normals=True):
    """Validate/weld an external triangle mesh before it reaches the renderer.

    FreeCAD/OpenCascade tolerate many malformed mesh files.  QPainter does not: NaN,
    invalid indices, duplicate/zero-area triangles and inconsistent winding can cause
    broken shading or even native crashes.  Keep the original geometric meaning while
    removing only invalid/redundant data.
    """
    vv=[]; remap={}
    for i,v in enumerate(vertices):
        q=_finite_vertex(v)
        if q is not None:
            remap[i]=len(vv);vv.append(q)
    tris=[];seen=set()
    for f in faces:
        try: ids=[remap[int(i)] for i in f if int(i) in remap]
        except Exception: continue
        if len(ids)<3:continue
        a=ids[0]
        for k in range(1,len(ids)-1):
            t=(a,ids[k],ids[k+1])
            if len(set(t))<3:continue
            p0,p1,p2=(vv[j] for j in t)
            ux,uy,uz=p1[0]-p0[0],p1[1]-p0[1],p1[2]-p0[2]
            vx,vy,vz=p2[0]-p0[0],p2[1]-p0[1],p2[2]-p0[2]
            nx,ny,nz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx
            if nx*nx+ny*ny+nz*nz < 1e-24:continue
            sk=tuple(sorted(t))
            if sk in seen:continue
            seen.add(sk);tris.append(t)
    if not vv or not tris:
        raise ValueError("3D 網格沒有有效的頂點／面，可能已損壞。")

    # Let trimesh weld close duplicates and repair winding when available.  The pure
    # Python validation above remains the fallback so importing never depends on it.
    if fix_normals:
        try:
            import trimesh
            m=trimesh.Trimesh(vertices=vv,faces=tris,process=False,validate=False)
            if hasattr(m,'remove_infinite_values'):m.remove_infinite_values()
            if hasattr(m,'nondegenerate_faces'):m.update_faces(m.nondegenerate_faces())
            if hasattr(m,'unique_faces'):m.update_faces(m.unique_faces())
            m.merge_vertices();m.remove_unreferenced_vertices()
            try:m.fix_normals(multibody=True)
            except TypeError:m.fix_normals()
            vv=[tuple(map(float,x[:3])) for x in m.vertices]
            tris=[tuple(map(int,x[:3])) for x in m.faces]
        except Exception:
            pass
    if not vv or not tris:raise ValueError("3D 網格清理後沒有可顯示的面。")
    return vv,tris


def _limited_edges(vertices, faces, cap=3500):
    """Stable picking/edit edge cache for imported triangle meshes.

    Prefer boundaries and sharp creases instead of arbitrary tessellation diagonals.
    A small deterministic sample of smooth mesh edges is retained so a closed smooth
    STL remains easy to pick even in TOP view.
    """
    adj={};normals=[]
    for fi,f in enumerate(faces):
        if len(f)<3:
            normals.append((0.0,0.0,0.0));continue
        try:
            a,b,c=(vertices[int(f[i])] for i in range(3))
            ux,uy,uz=b[0]-a[0],b[1]-a[1],b[2]-a[2];vx,vy,vz=c[0]-a[0],c[1]-a[1],c[2]-a[2]
            nx,ny,nz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx;L=(nx*nx+ny*ny+nz*nz)**0.5
            n=(0.0,0.0,0.0) if L<1e-15 else (nx/L,ny/L,nz/L)
        except Exception:
            n=(0.0,0.0,0.0)
        normals.append(n)
        ids=[int(x) for x in f[:3]]
        for u,v in ((ids[0],ids[1]),(ids[1],ids[2]),(ids[2],ids[0])):
            k=(u,v) if u<v else (v,u);arr=adj.setdefault(k,[])
            if len(arr)<4:arr.append(fi)
    ct=math.cos(math.radians(34.0));features=[];smooth=[]
    for e,fl in adj.items():
        keep=len(fl)!=2
        if not keep:
            n0,n1=normals[fl[0]],normals[fl[1]]
            keep=(n0[0]*n1[0]+n0[1]*n1[1]+n0[2]*n1[2])<ct
        (features if keep else smooth).append(e)
    # Preserve all important edges first.  Only a completely smooth closed mesh needs
    # a sparse tessellation sample for TOP-view picking; otherwise do not pollute the
    # feature cache with triangle diagonals.
    if len(features)>=cap:
        step=max(1,len(features)//cap);return features[::step][:cap]
    if len(features)<4 and smooth:
        room=cap-len(features);sample_cap=min(room,max(300,cap//3))
        step=max(1,len(smooth)//max(1,sample_cap));features.extend(smooth[::step][:sample_cap])
    return features[:cap]


def _solid_from_mesh(vertices, faces, shape='IMPORTED', fix_normals=True):
    vv,ff=_sanitize_mesh(vertices,faces,fix_normals=fix_normals)
    solid=Solid3D(vertices=vv,edges=_limited_edges(vv,ff),faces=[list(f) for f in ff],shape=shape)
    # Build/cache a safe display LOD now, while import is already doing heavy work.
    # This prevents the first mouse move from suddenly allocating hundreds of MB.
    try:solid.display_mesh(50000)
    except Exception:pass
    solid.__dict__['_import_stats']={'vertices':len(vv),'faces':len(ff)}
    return solid


def _bounded_step_mesh(vertices, faces, max_faces=70000):
    """STEP keeps exact BREP, so its stored mesh may safely be display-resolution."""
    tmp=_solid_from_mesh(vertices,faces,'STEP',fix_normals=False)
    if len(tmp.faces)<=max_faces:return tmp.vertices,tmp.faces
    vv,ff,_=tmp.display_mesh(max_faces)
    return vv,[list(f) for f in ff]


def import_obj(path, scale=1.0):
    v=[]; faces=[]
    with open(path,'r',encoding='utf-8',errors='ignore') as f:
        for line in f:
            t=line.strip().split()
            if not t:continue
            if t[0]=='v' and len(t)>=4:
                try:v.append((float(t[1])*scale,float(t[2])*scale,float(t[3])*scale))
                except ValueError:continue
            elif t[0]=='f' and len(t)>=4:
                ids=[]
                for q in t[1:]:
                    try:
                        i=int(q.split('/')[0]);ids.append(i-1 if i>0 else len(v)+i)
                    except ValueError:pass
                if len(ids)>=3:faces.append(ids)
    if not v or not faces:raise ValueError("OBJ 中找不到可用的網格。")
    return [_solid_from_mesh(v,faces,'OBJ')]


def import_off(path, scale=1.0):
    with open(path,'r',encoding='ascii',errors='ignore') as f:
        lines=[x.strip() for x in f if x.strip() and not x.lstrip().startswith('#')]
    if not lines or lines[0] != 'OFF':raise ValueError("不是有效的 OFF 檔。")
    nv,nf,_=map(int,lines[1].split()[:3]);v=[tuple(float(x)*scale for x in lines[2+i].split()[:3]) for i in range(nv)]
    faces=[];pos=2+nv
    for i in range(nf):
        a=list(map(int,lines[pos+i].split()));faces.append(a[1:1+a[0]])
    return [_solid_from_mesh(v,faces,'OFF')]


def import_ply(path, scale=1.0):
    with open(path,'r',encoding='ascii',errors='ignore') as f:lines=f.readlines()
    if not lines or lines[0].strip()!='ply':raise ValueError("目前 PLY 匯入支援 ASCII PLY。")
    nv=nf=0;end=0
    for i,line in enumerate(lines):
        t=line.strip().split()
        if t[:2]==['format','binary_little_endian']:raise ValueError("目前 PLY 匯入支援 ASCII PLY。")
        if t[:2]==['element','vertex']:nv=int(t[2])
        if t[:2]==['element','face']:nf=int(t[2])
        if line.strip()=='end_header':end=i+1;break
    v=[tuple(float(x)*scale for x in lines[end+i].split()[:3]) for i in range(nv)]
    faces=[];pos=end+nv
    for i in range(nf):
        a=list(map(int,lines[pos+i].split()));faces.append(a[1:1+a[0]])
    return [_solid_from_mesh(v,faces,'PLY')]


def _clean_trimesh(m):
    """Best-effort cleanup across trimesh versions without requiring optional extras."""
    try:m=m.copy()
    except Exception:pass
    try:
        if hasattr(m,'remove_infinite_values'):m.remove_infinite_values()
        if hasattr(m,'nondegenerate_faces'):m.update_faces(m.nondegenerate_faces())
        if hasattr(m,'unique_faces'):m.update_faces(m.unique_faces())
        m.merge_vertices();m.remove_unreferenced_vertices()
        try:m.fix_normals(multibody=True)
        except TypeError:m.fix_normals()
    except Exception:pass
    return m


def import_stl(path, scale=1.0):
    # Robust binary/ASCII STL path.  Do not feed raw duplicated facet vertices to Qt.
    try:
        import trimesh
        m=trimesh.load(path,force='mesh',process=False)
        if hasattr(m,'geometry'):
            geoms=[g for g in m.geometry.values() if hasattr(g,'vertices') and len(g.vertices)]
            if not geoms:raise ValueError("STL 中沒有可用網格。")
            m=trimesh.util.concatenate(tuple(geoms))
        m=_clean_trimesh(m)
        return [_solid_from_mesh([(float(x)*scale,float(y)*scale,float(z)*scale) for x,y,z in m.vertices],m.faces,'STL',fix_normals=False)]
    except Exception as first_error:
        # Dependency-free fallback is intentionally ASCII-only.
        verts=[];faces=[];index={}
        try:
            with open(path,'r',encoding='ascii',errors='ignore') as f:
                tri=[]
                for line in f:
                    t=line.strip().split()
                    if len(t)==4 and t[0].lower()=='vertex':
                        q=tuple(float(x)*scale for x in t[1:4]);idx=index.setdefault(q,len(index))
                        if idx==len(verts):verts.append(q)
                        tri.append(idx)
                        if len(tri)==3:faces.append(tuple(tri));tri=[]
            if not verts or not faces:raise ValueError("無法讀取 STL；若為 binary STL，請確認 trimesh 已正確安裝。")
            return [_solid_from_mesh(verts,faces,'STL')]
        except Exception:
            raise ValueError("STL 匯入失敗：%s"%first_error) from first_error


def _step_tessellate_safe(shape, face_budget=70000):
    """Scale-aware tessellation for viewing; exact STEP BREP remains authoritative."""
    try:
        bb=shape.BoundingBox();diag=max((bb.xlen*bb.xlen+bb.ylen*bb.ylen+bb.zlen*bb.zlen)**0.5,1e-6)
    except Exception:
        diag=100.0
    # Relative deflection avoids tiny parts looking faceted and metre-scale machines
    # producing millions of microscopic triangles.
    tol=max(diag/900.0,1e-5)
    last=None
    for _ in range(4):
        verts,tris=shape.tessellate(tol)
        last=(verts,tris)
        if len(tris)<=face_budget*1.35:break
        tol*=1.8
    verts,tris=last
    vv=[(float(v.x),float(v.y),float(v.z)) for v in verts]
    if len(tris)>face_budget:
        vv,ff=_bounded_step_mesh(vv,tris,face_budget)
        return vv,ff
    return vv,[list(map(int,t)) for t in tris]


def import_step(path, scale=1.0):
    try:
        import cadquery as cq
    except Exception as ex:raise RuntimeError("STEP 匯入需要 CadQuery。請執行：pip install cadquery") from ex
    shape=cq.importers.importStep(path)
    vals=shape.vals() if hasattr(shape,'vals') else [shape.val()]
    vals=[x for x in vals if x is not None]
    if not vals:raise ValueError("STEP 中找不到可用的 3D 幾何。")
    # Keep a total display budget for assemblies with many bodies.
    per=max(8000,min(70000,140000//max(1,len(vals))))
    out=[];errors=[]
    for sh in vals:
        target=sh
        if abs(float(scale)-1.0)>=1e-12:
            try:
                m=cq.Matrix([[scale,0,0,0],[0,scale,0,0],[0,0,scale,0],[0,0,0,1]])
                target=sh.transformGeometry(m)
            except Exception as ex:
                errors.append(str(ex));target=None
        try:
            if target is not None:
                vv,ff=_step_tessellate_safe(target,per)
                solid=_solid_from_mesh(vv,ff,'STEP',fix_normals=True)
                try:solid.brep_b64=_shape_to_brep_b64(target)
                except Exception:pass
            else:
                vv0,ff=_step_tessellate_safe(sh,per)
                vv=[(x*scale,y*scale,z*scale) for x,y,z in vv0]
                solid=_solid_from_mesh(vv,ff,'STEP',fix_normals=True)
            out.append(solid)
        except Exception as ex:
            errors.append(str(ex))
    if not out:
        raise ValueError("STEP 幾何無法安全三角化："+(errors[-1] if errors else "未知錯誤"))
    return out


def _import_trimesh_scene(path, scale=1.0, shape="MESH"):
    try:
        import trimesh
    except Exception as ex:
        raise RuntimeError("此格式匯入需要 trimesh。請執行：pip install trimesh") from ex
    data=trimesh.load(path,force='scene',process=False)
    if hasattr(data,'geometry'):
        # Scene.dump applies node transforms.  Reading raw geometry.values() loses
        # assembly placement and is a common cause of overlapping/'broken' models.
        try:geoms=list(data.dump(concatenate=False))
        except Exception:geoms=list(data.geometry.values())
    else:geoms=[data]
    out=[]
    for m in geoms:
        if not hasattr(m,'vertices') or not hasattr(m,'faces') or len(m.vertices)==0:continue
        m=_clean_trimesh(m)
        try:out.append(_solid_from_mesh([(float(x)*scale,float(y)*scale,float(z)*scale) for x,y,z in m.vertices],m.faces,shape,fix_normals=False))
        except ValueError:continue
    if not out:raise ValueError("檔案中找不到可安全匯入的三角網格。")
    return out



# ================================================================ v0.6.3 additional interchange formats
def export_amf(path, doc):
    """Export additive-manufacturing AMF (XML, millimetres)."""
    import xml.etree.ElementTree as ET
    solids=_solid3d(doc)
    if not solids: raise ValueError("圖面中沒有可匯出的 3D 實體。")
    scale=_to_mm(doc); root=ET.Element('amf',unit='millimeter',version='1.1')
    for oi,solid in enumerate(solids):
        obj=ET.SubElement(root,'object',id=str(oi)); mesh=ET.SubElement(obj,'mesh'); verts=ET.SubElement(mesh,'vertices')
        for x,y,z in solid.vertices:
            ve=ET.SubElement(verts,'vertex'); co=ET.SubElement(ve,'coordinates')
            ET.SubElement(co,'x').text=str(float(x)*scale); ET.SubElement(co,'y').text=str(float(y)*scale); ET.SubElement(co,'z').text=str(float(z)*scale)
        vol=ET.SubElement(mesh,'volume')
        for a,b,c in [(solid.vertices.index(t[0]), solid.vertices.index(t[1]), solid.vertices.index(t[2])) for t in _triangles(solid)]:
            tr=ET.SubElement(vol,'triangle'); ET.SubElement(tr,'v1').text=str(a); ET.SubElement(tr,'v2').text=str(b); ET.SubElement(tr,'v3').text=str(c)
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)


def import_amf(path, scale=1.0):
    import xml.etree.ElementTree as ET
    root=ET.parse(path).getroot(); out=[]
    for obj in root.findall('.//object'):
        vs=[]; fs=[]; mesh=obj.find('mesh')
        if mesh is None: continue
        verts=mesh.find('vertices')
        if verts is not None:
            for ve in verts.findall('vertex'):
                co=ve.find('coordinates')
                if co is not None:
                    vs.append((float(co.findtext('x','0'))*scale,float(co.findtext('y','0'))*scale,float(co.findtext('z','0'))*scale))
        for tr in mesh.findall('.//triangle'):
            fs.append((int(tr.findtext('v1','0')),int(tr.findtext('v2','0')),int(tr.findtext('v3','0'))))
        if vs and fs: out.append(_solid_from_mesh(vs,fs,'AMF'))
    if not out: raise ValueError("AMF 中找不到可匯入的網格。")
    return out


def export_wrl(path, doc):
    """Export VRML97 IndexedFaceSet; useful for legacy CAD/3D viewers."""
    solids=_solid3d(doc)
    if not solids: raise ValueError("圖面中沒有可匯出的 3D 實體。")
    scale=_to_mm(doc)
    with open(path,'w',encoding='utf-8') as f:
        f.write('#VRML V2.0 utf8\nWorldInfo { title "PyCAD v0.6.9.4" }\n')
        for solid in solids:
            f.write('Shape { geometry IndexedFaceSet { solid TRUE coord Coordinate { point [\n')
            for x,y,z in solid.vertices: f.write(' %.12g %.12g %.12g,\n'%(x*scale,y*scale,z*scale))
            f.write('] } coordIndex [\n')
            for face in solid.faces:
                ids=[int(i) for i in face if 0<=int(i)<len(solid.vertices)]
                if len(ids)>=3:f.write(' '+', '.join(map(str,ids))+', -1,\n')
            f.write('] } }\n')




def import_wrl(path, scale=1.0):
    """Read all common VRML97 IndexedFaceSet meshes, not only the first Shape."""
    import re
    text=open(path,'r',encoding='utf-8',errors='ignore').read();out=[]
    pat=re.compile(r'point\s*\[(.*?)\].*?coordIndex\s*\[(.*?)\]',re.I|re.S)
    for pm in pat.finditer(text):
        nums=[float(x) for x in re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?',pm.group(1))]
        verts=[(nums[i]*scale,nums[i+1]*scale,nums[i+2]*scale) for i in range(0,len(nums)-2,3)]
        ids=[int(x) for x in re.findall(r'-?\d+',pm.group(2))];faces=[];cur=[]
        for i in ids:
            if i==-1:
                if len(cur)>=3:faces.append(cur)
                cur=[]
            else:cur.append(i)
        if len(cur)>=3:faces.append(cur)
        if verts and faces:out.append(_solid_from_mesh(verts,faces,'VRML'))
    if not out:raise ValueError("VRML 中找不到可用的 IndexedFaceSet 網格。")
    return out


def export_dae(path, doc):
    scene=_trimesh_scene(doc)
    try:data=scene.export(file_type='dae')
    except Exception as ex: raise RuntimeError("DAE/Collada 匯出需要 trimesh + pycollada。請執行：pip install trimesh pycollada") from ex
    with open(path,'wb' if isinstance(data,(bytes,bytearray)) else 'w') as f:f.write(data)

def import_3d(path, doc=None):
    ext=os.path.splitext(path)[1].lower(); scale=1.0
    # imported interchange files are treated as millimetres; convert to document units.
    if doc is not None:
        mm=_to_mm(doc); scale=1.0/mm if mm else 1.0
    if ext=='.obj':return import_obj(path,scale)
    if ext=='.stl':return import_stl(path,scale)
    if ext=='.ply':return import_ply(path,scale)
    if ext=='.off':return import_off(path,scale)
    if ext in ('.step','.stp'):return import_step(path,scale)
    if ext in ('.glb','.gltf','.3mf','.dae'):return _import_trimesh_scene(path,scale,ext[1:].upper())
    if ext=='.amf':return import_amf(path,scale)
    if ext in ('.wrl','.vrml'):return import_wrl(path,scale)
    raise ValueError("尚未支援此 3D 格式："+ext)

# ================================================================ DWG（透過 ODA File Converter）
def find_oda():
    exe = shutil.which("ODAFileConverter") or shutil.which("ODAFileConverter.exe")
    if exe:
        return exe
    cands = glob.glob(r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe") + \
        glob.glob("/usr/bin/ODAFileConverter*") + glob.glob("/opt/ODAFileConverter*/ODAFileConverter*") + \
        glob.glob("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter")
    return cands[0] if cands else None


def _oda(src_dir, dst_dir, out_ver, out_type, flt):
    exe = find_oda()
    if not exe:
        raise RuntimeError("找不到 ODA File Converter。\n\nDWG 是專有格式，PyCAD 需要透過免費的 ODA File Converter 轉檔。\n"
                           "請到 opendesign.com 下載安裝後再試，或先在 CAD 軟體中另存成 DXF。")
    # ODA File Converter ships its own Qt runtime.  Inheriting PyCAD's Qt plugin
    # environment (especially QT_QPA_PLATFORM=offscreen) can make ODA fail before
    # conversion starts on Windows, so explicitly sanitize those variables.
    env = {k: v for k, v in os.environ.items()
           if k not in ("QT_QPA_PLATFORM", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH")}
    kw = {}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kw["startupinfo"] = si
    try:
        cp = subprocess.run([exe, src_dir, dst_dir, out_ver, out_type, "0", "1", flt],
                            check=False, timeout=300, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **kw)
    except subprocess.TimeoutExpired as ex:
        raise RuntimeError("ODA File Converter 超過 5 分鐘沒有回應，已中止轉檔。") from ex
    if cp.returncode not in (0, None):
        raise RuntimeError("ODA File Converter 轉檔失敗（錯誤碼 %s）。" % cp.returncode)

def import_dwg(path):
    src, dst = tempfile.mkdtemp(prefix="pycad_in_"), tempfile.mkdtemp(prefix="pycad_out_")
    try:
        shutil.copy(path, os.path.join(src, "in.dwg"))
        _oda(src, dst, "ACAD2018", "DXF", "*.dwg")
        out = glob.glob(os.path.join(dst, "*.dxf")) + glob.glob(os.path.join(dst, "*.DXF"))
        if not out:
            raise RuntimeError("ODA File Converter 沒有產生 DXF，轉檔失敗。")
        doc = import_dxf(out[0])
        doc.source = "DWG"
        return doc
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


def export_dwg(path, doc):
    if not have_ezdxf():
        raise RuntimeError("匯出 DWG 需要先安裝 ezdxf（pip install ezdxf）以及 ODA File Converter。")
    src, dst = tempfile.mkdtemp(prefix="pycad_in_"), tempfile.mkdtemp(prefix="pycad_out_")
    try:
        export_dxf_2010(os.path.join(src, "out.dxf"), doc)
        _oda(src, dst, "ACAD2018", "DWG", "*.dxf")
        out = glob.glob(os.path.join(dst, "*.dwg")) + glob.glob(os.path.join(dst, "*.DWG"))
        if not out:
            raise RuntimeError("ODA File Converter 沒有產生 DWG，轉檔失敗。")
        shutil.copy(out[0], path)
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)
