# SPDX-License-Identifier: GPL-3.0-only
"""指令定義。

每個指令都是一個 generator：用 yield 向畫布要求輸入（點、選集、數字、關鍵字、文字），
畫布把使用者的輸入 send 回來。這樣提示流程可以寫得跟 AutoCAD 指令行一樣。
"""
import math
from dataclasses import dataclass
from . import geometry as G
from . import edit_ops as E
from .model import (Line, Circle, Arc, Polyline, Ellipse, Spline, Point, Text, MText, Hatch, XLine, Dim, Insert, Array, Solid3D,
                    Block, fmt, color_name, lw_name, TWO_PI)


class Kw(str):
    """使用者選了某個關鍵字選項。"""


@dataclass
class Req:
    kind: str                 # point / select / entity / text / num / kw
    prompt: str
    keywords: tuple = ()      # (("C", "閉合"), ...)
    default: object = None
    base: tuple = None        # 橡皮筋線的基準點
    preview: object = None    # fn(pt) -> [圖元]
    number: bool = False      # point 要求：輸入數字時直接回傳 float
    rubber: bool = True
    types: tuple = None
    show_default: object = None
    face_pick: bool = False      # point request must acquire a visible Solid3D face


def pt(prompt, base=None, kw=(), preview=None, number=False, default=None, rubber=True, show=None, face_pick=False):
    return Req("point", prompt, tuple(kw), default, base, preview, number, rubber, None, show, bool(face_pick))


def sel(prompt="選取物件"):
    return Req("select", prompt)


def ent(prompt, kw=(), types=None):
    return Req("entity", prompt, tuple(kw), types=types)


def txt(prompt, default=None):
    return Req("text", prompt, default=default)


def num(prompt, default=None, kw=()):
    return Req("num", prompt, tuple(kw), default)


def kwd(prompt, kws, default=None):
    return Req("kw", prompt, tuple(kws), default)


def is_pt(v):
    return isinstance(v, tuple)


def _rect_pts(a, b):
    return [(a[0], a[1], 0.0), (b[0], a[1], 0.0), (b[0], b[1], 0.0), (a[0], b[1], 0.0)]


def _xform(ents, m, limit=400):
    return [e.transformed(m) for e in ents[:limit]]


def _copy_preview_xyz(ents, base, q, limit=400):
    """Cheap COPY preview that honours XYZ for Solid3D without rebuilding BREP."""
    dx=float(q[0])-float(base[0]); dy=float(q[1])-float(base[1])
    dz=(float(q[2]) if len(q)>=3 else 0.0)-(float(base[2]) if len(base)>=3 else 0.0)
    m=G.m_translate(dx,dy); out=[]
    for e in ents[:limit]:
        if isinstance(e,Solid3D):
            out.append(e.clone(vertices=[(x+dx,y+dy,z+dz) for x,y,z in e.vertices],brep_b64=""))
        else:
            out.append(e.transformed(m))
    return out


def _solid_exact_transform(e, kind, *args):
    """Preserve an exact BREP when 2D transform commands touch a Solid3D."""
    if not isinstance(e,Solid3D):
        return None
    try:
        from .io_utils import _cq_shape_from_solid,_shape_to_brep_b64
        sh=_cq_shape_from_solid(e,1.0)
        if kind=="MOVE":
            dx,dy=args; sh=sh.translate((float(dx),float(dy),0.0))
        elif kind=="ROTATE":
            base,ang=args; sh=sh.rotate((base[0],base[1],0.0),(base[0],base[1],1.0),float(ang))
        elif kind=="SCALE":
            base,k=args; sh=sh.translate((-base[0],-base[1],0.0)).scale(float(k)).translate((base[0],base[1],0.0))
        elif kind=="MIRROR":
            a,b=args; dx,dy=b[0]-a[0],b[1]-a[1];L=math.hypot(dx,dy)
            if L<G.EPS:return None
            normal=(-dy/L,dx/L,0.0); sh=sh.mirror(normal,basePointVector=(a[0],a[1],0.0))
        else:return None
        return _shape_to_brep_b64(sh)
    except Exception:
        return None

# ================================================================ 繪製
def LINE(c):
    p = yield pt("指定第一點")
    if not is_pt(p):
        return
    pts, made = [p], []
    while True:
        kws = (("C", "閉合"), ("U", "退回")) if len(pts) >= 3 else (("U", "退回"),)
        q = yield pt("指定下一點或", base=pts[-1], kw=kws)
        if q is None:
            return
        if q == "U":
            if made:
                c.remove([made.pop()])
                pts.pop()
            continue
        if q == "C":
            c.add(c.make(Line, x1=pts[-1][0], y1=pts[-1][1], x2=pts[0][0], y2=pts[0][1]))
            return
        if is_pt(q) and G.dist(q, pts[-1]) > G.EPS:
            made.append(c.add(c.make(Line, x1=pts[-1][0], y1=pts[-1][1], x2=q[0], y2=q[1])))
            pts.append(q)


def _end_tangent(pts):
    """聚合線目前最後一段在終點的切線方向。"""
    if len(pts) < 2:
        return 0.0
    a, b = pts[-2], pts[-1]
    ch = G.ang(a, b)
    return (ch + math.degrees(2 * math.atan(a[2]))) % 360.0


def _arc_bulge(pts, q):
    last = pts[-1]
    if G.dist(last, q) < G.EPS:
        return 0.0
    phi = math.radians((G.ang(last, q) - _end_tangent(pts) + 180.0) % 360.0 - 180.0)
    if abs(abs(phi) - math.pi) < 1e-9:
        return 0.0
    return math.tan(phi / 2.0)


def PLINE(c):
    p = yield pt("指定起點")
    if not is_pt(p):
        return
    pts = [(p[0], p[1], 0.0)]
    arc = False
    closed = False

    def build(q):
        ps = list(pts)
        if arc:
            ps[-1] = (ps[-1][0], ps[-1][1], _arc_bulge(pts, q))
        return ps + [(q[0], q[1], 0.0)]

    while True:
        kws = ((("L", "直線"),) if arc else (("A", "弧"),)) + (("C", "閉合"), ("U", "退回"))
        q = yield pt("指定弧的端點或" if arc else "指定下一點或", base=pts[-1][:2], kw=kws,
                     preview=lambda q: [c.make(Polyline, pts=build(q))], rubber=not arc)
        if q is None:
            break
        if q == "A":
            arc = True
        elif q == "L":
            arc = False
        elif q == "U":
            if len(pts) > 1:
                pts.pop()
                pts[-1] = (pts[-1][0], pts[-1][1], 0.0)
        elif q == "C":
            if len(pts) >= 2:
                if arc:
                    pts[-1] = (pts[-1][0], pts[-1][1], _arc_bulge(pts, pts[0][:2]))
                closed = True
            break
        elif is_pt(q) and G.dist(q, pts[-1]) > G.EPS:
            pts[:] = build(q)
    if len(pts) >= 2:
        c.add(c.make(Polyline, pts=pts, closed=closed))


def CIRCLE(c):
    p = yield pt("指定圓的中心點或", kw=(("3P", "三點"), ("2P", "兩點")))
    if p == "2P":
        a = yield pt("指定圓直徑的第一個端點")
        if not is_pt(a):
            return
        mk = lambda q: c.make(Circle, cx=(a[0] + q[0]) / 2, cy=(a[1] + q[1]) / 2, r=G.dist(a, q) / 2)
        b = yield pt("指定圓直徑的第二個端點", base=a, preview=lambda q: [mk(q)])
        if is_pt(b) and G.dist(a, b) > G.EPS:
            c.add(mk(b))
        return
    if p == "3P":
        a = yield pt("指定圓上的第一點")
        if not is_pt(a):
            return
        b = yield pt("指定圓上的第二點", base=a)
        if not is_pt(b):
            return

        def mk(q):
            cc = G.circle_3p(a, b, q)
            return [c.make(Circle, cx=cc[0], cy=cc[1], r=cc[2])] if cc else []

        d = yield pt("指定圓上的第三點", preview=mk)
        if is_pt(d):
            r = mk(d)
            if r:
                c.add(r[0])
            else:
                c.msg("三點共線，無法建立圓。")
        return
    if not is_pt(p):
        return
    last = c.doc.vars.get("CIRCLERAD", 0.0)
    r = yield pt("指定圓的半徑或", base=p, kw=(("D", "直徑"),), number=True, default=last if last > 0 else None,
                 preview=lambda q: [c.make(Circle, cx=p[0], cy=p[1], r=G.dist(p, q))])
    if r == "D":
        r = yield pt("指定圓的直徑", base=p, number=True,
                     preview=lambda q: [c.make(Circle, cx=p[0], cy=p[1], r=G.dist(p, q) / 2)])
        if r is None or isinstance(r, Kw):
            return
        r = (G.dist(p, r) if is_pt(r) else float(r)) / 2.0
    elif is_pt(r):
        r = G.dist(p, r)
    if isinstance(r, (int, float)) and r > G.EPS:
        c.doc.vars["CIRCLERAD"] = float(r)
        c.add(c.make(Circle, cx=p[0], cy=p[1], r=float(r)))


def ARC(c):
    p1 = yield pt("指定弧的起點或", kw=(("C", "中心點"),))
    if p1 == "C":
        cen = yield pt("指定弧的中心點")
        if not is_pt(cen):
            return
        s = yield pt("指定弧的起點", base=cen)
        if not is_pt(s):
            return
        mk = lambda q: c.make(Arc, cx=cen[0], cy=cen[1], r=G.dist(cen, s), a0=G.ang(cen, s), a1=G.ang(cen, q))
        e = yield pt("指定弧的終點", base=cen, preview=lambda q: [mk(q)])
        if is_pt(e):
            c.add(mk(e))
        return
    if not is_pt(p1):
        return
    p2 = yield pt("指定弧的第二點", base=p1)
    if not is_pt(p2):
        return

    def mk(q):
        a = G.arc_3p(p1, p2, q)
        return [c.make(Arc, cx=a[0], cy=a[1], r=a[2], a0=a[3], a1=a[4])] if a else []

    p3 = yield pt("指定弧的終點", preview=mk)
    if is_pt(p3):
        r = mk(p3)
        if r:
            c.add(r[0])
        else:
            c.msg("三點共線，無法建立弧。")


def RECTANG(c):
    a = yield pt("指定第一個角點")
    if not is_pt(a):
        return
    b = yield pt("指定另一個角點或", base=a, kw=(("D", "尺寸"),), rubber=False,
                 preview=lambda q: [c.make(Polyline, pts=_rect_pts(a, q), closed=True)])
    if b == "D":
        w = yield num("指定矩形的長度", default=c.doc.vars.get("RECTW", 10.0))
        h = yield num("指定矩形的寬度", default=c.doc.vars.get("RECTH", 10.0))
        if not isinstance(w, (int, float)) or not isinstance(h, (int, float)):
            return
        c.doc.vars["RECTW"], c.doc.vars["RECTH"] = w, h
        corner = lambda q: (a[0] + (w if q[0] >= a[0] else -w), a[1] + (h if q[1] >= a[1] else -h))
        q = yield pt("指定另一個角點（決定方向）", base=a, rubber=False,
                     preview=lambda q: [c.make(Polyline, pts=_rect_pts(a, corner(q)), closed=True)])
        b = corner(q) if is_pt(q) else (a[0] + w, a[1] + h)
    if is_pt(b) and abs(b[0] - a[0]) > G.EPS and abs(b[1] - a[1]) > G.EPS:
        c.add(c.make(Polyline, pts=_rect_pts(a, b), closed=True))


def POLYGON(c):
    n = yield num("輸入邊數", default=c.doc.vars.get("POLYSIDES", 4))
    if not isinstance(n, (int, float)) or int(n) < 3 or int(n) > 1024:
        c.msg("邊數必須介於 3 到 1024。")
        return
    n = int(n)
    c.doc.vars["POLYSIDES"] = n
    cen = yield pt("指定多邊形的中心點")
    if not is_pt(cen):
        return
    mode = yield kwd("輸入選項", (("I", "內接於圓"), ("C", "外切於圓")), default=Kw("I"))

    def mk(r):
        if is_pt(r):
            rad, a0 = G.dist(cen, r), G.ang(cen, r)
            if mode == "C":
                rad, a0 = rad / math.cos(math.pi / n), a0 + 180.0 / n
        else:
            rad = float(r) / (math.cos(math.pi / n) if mode == "C" else 1.0)
            a0 = 270.0 - 180.0 / n
        return c.make(Polyline, closed=True,
                      pts=[G.polar(cen, a0 + 360.0 * i / n, rad) + (0.0,) for i in range(n)])

    r = yield pt("指定圓的半徑", base=cen, number=True, preview=lambda q: [mk(q)])
    if r is not None and not isinstance(r, Kw) and (is_pt(r) or r > 0):
        c.add(mk(r))


def ELLIPSE(c):
    p1 = yield pt("指定橢圓的軸端點或", kw=(("C", "中心點"),))
    if p1 == "C":
        cen = yield pt("指定橢圓的中心點")
        if not is_pt(cen):
            return
        p2 = yield pt("指定軸的端點", base=cen)
        if not is_pt(p2):
            return
    elif is_pt(p1):
        p2 = yield pt("指定軸的另一個端點", base=p1)
        if not is_pt(p2):
            return
        cen = G.mid(p1, p2)
    else:
        return
    half = G.dist(cen, p2)
    if half < G.EPS:
        return

    def mk(d):
        d = G.dist(cen, d) if is_pt(d) else float(d)
        if d < G.EPS:
            return None
        mx, my = p2[0] - cen[0], p2[1] - cen[1]
        if d <= half:
            return c.make(Ellipse, cx=cen[0], cy=cen[1], mx=mx, my=my, ratio=d / half)
        k = d / half
        return c.make(Ellipse, cx=cen[0], cy=cen[1], mx=-my * k, my=mx * k, ratio=half / d)

    d = yield pt("指定到另一軸的距離", base=cen, number=True, preview=lambda q: [x for x in [mk(q)] if x])
    if d is not None and not isinstance(d, Kw):
        e = mk(d)
        if e:
            c.add(e)


def SPLINE(c):
    p = yield pt("指定第一點")
    if not is_pt(p):
        return
    fit = [p]
    closed = False
    while True:
        kws = (("C", "閉合"), ("U", "退回")) if len(fit) >= 3 else (("U", "退回"),)
        q = yield pt("輸入下一點或", base=fit[-1], kw=kws, rubber=False,
                     preview=lambda q: [c.make(Spline, fit=fit + [q])])
        if q is None:
            break
        if q == "U":
            if len(fit) > 1:
                fit.pop()
        elif q == "C":
            closed = True
            break
        elif is_pt(q) and G.dist(q, fit[-1]) > G.EPS:
            fit.append(q)
    if len(fit) >= 2:
        c.add(c.make(Spline, fit=fit, closed=closed))


def XLINE(c, ray=False):
    kws = () if ray else (("H", "水平"), ("V", "垂直"), ("A", "角度"))
    p = yield pt("指定起點" if ray else "指定點或", kw=kws)
    fixed = None
    if p == "H":
        fixed = (1.0, 0.0)
    elif p == "V":
        fixed = (0.0, 1.0)
    elif p == "A":
        a = yield num("輸入建構線的角度", default=0.0)
        if not isinstance(a, (int, float)):
            return
        fixed = (math.cos(math.radians(a)), math.sin(math.radians(a)))
    if fixed:
        while True:
            q = yield pt("指定通過點", preview=lambda q: [c.make(XLine, x=q[0], y=q[1], dx=fixed[0], dy=fixed[1])])
            if not is_pt(q):
                return
            c.add(c.make(XLine, x=q[0], y=q[1], dx=fixed[0], dy=fixed[1]))
    if not is_pt(p):
        return
    while True:
        mk = lambda q: c.make(XLine, x=p[0], y=p[1], dx=q[0] - p[0], dy=q[1] - p[1], ray=ray)
        q = yield pt("指定通過點", base=p, preview=lambda q: [mk(q)] if G.dist(p, q) > G.EPS else [])
        if not is_pt(q):
            return
        if G.dist(p, q) > G.EPS:
            c.add(mk(q))


def RAY(c):
    yield from XLINE(c, ray=True)


def POINT(c):
    while True:
        p = yield pt("指定點")
        if not is_pt(p):
            return
        c.add(c.make(Point, x=p[0], y=p[1]))


def TEXT(c):
    p = yield pt("指定文字的起點")
    if not is_pt(p):
        return
    h = yield pt("指定高度", base=p, number=True, default=c.doc.vars["TEXTSIZE"])
    h = G.dist(p, h) if is_pt(h) else h
    if not isinstance(h, (int, float)) or h <= 0:
        return
    c.doc.vars["TEXTSIZE"] = float(h)
    r = yield pt("指定文字的旋轉角度", base=p, number=True, default=0.0)
    r = G.ang(p, r) if is_pt(r) else r
    if not isinstance(r, (int, float)):
        return
    line = 0
    while True:
        s = yield txt("輸入文字")
        if not s:
            return
        q = G.polar(p, r - 90.0, line * h * 5.0 / 3.0)
        c.add(c.make(Text, x=q[0], y=q[1], text=s, height=float(h), rot=float(r) % 360.0))
        line += 1


def MTEXT(c):
    a = yield pt("指定第一角點")
    if not is_pt(a):
        return
    b = yield pt("指定對角點", base=a, rubber=False,
                 preview=lambda q: [c.make(Polyline, pts=_rect_pts(a, q), closed=True)])
    if not is_pt(b):
        return
    h = c.doc.vars["TEXTSIZE"]
    s = c.ui.ask_text("多行文字", "") if c.ui else None
    if c.ui is None:
        s = yield txt("輸入文字（\\P 換行）")
        s = s.replace("\\P", "\n") if s else s
    if s:
        c.add(c.make(MText, x=min(a[0], b[0]), y=max(a[1], b[1]), text=s, height=h, width=abs(b[0] - a[0]), attach=1))


def HATCH(c):
    v = c.doc.vars
    c.msg("目前的設定: 樣式 = %s, 比例 = %s, 角度 = %s" % (v["HPNAME"], fmt(v["HPSCALE"]), fmt(v["HPANG"])))
    made = None
    while True:
        p = yield pt("點選內部點或", kw=(("S", "選取物件"), ("P", "樣式"), ("SC", "比例"), ("A", "角度"), ("U", "退回")))
        if p is None:
            return
        if p == "P":
            from .render import HATCH_PATTERNS
            pats = tuple((name, name) for name in sorted(HATCH_PATTERNS))
            k = yield kwd("輸入樣式名稱", pats, default=Kw(v["HPNAME"]))
            v["HPNAME"] = str(k)
            continue
        if p == "SC":
            s = yield num("指定樣式比例", default=v["HPSCALE"])
            if isinstance(s, (int, float)) and s > 0:
                v["HPSCALE"] = float(s)
            continue
        if p == "A":
            s = yield num("指定樣式角度", default=v["HPANG"])
            if isinstance(s, (int, float)):
                v["HPANG"] = float(s)
            continue
        if p == "U":
            if made is not None:
                c.remove([made])
                made = None
            continue
        loops, loop_prims, boundary_uids = [], [], []
        if p == "S":
            s = yield sel()
            for e in s or []:
                o = E.closed_outline(e)
                if o:
                    loops.append(o)
                    loop_prims.append([tuple(pr) for pr in e.prims()])
                    boundary_uids.append([e.uid])
            if not loops:
                c.msg("選取的物件沒有封閉邊界。")
                continue
        elif is_pt(p):
            loops = E.find_boundary(c.doc, p, c.view_rect())
            loop_prims = []
            boundary_uids = []
            if not loops:
                c.msg("找不到有效的封閉邊界。")
                continue
        if made is None:
            made = c.add(c.make(Hatch, loops=loops, loop_prims=loop_prims, boundary_uids=boundary_uids,
                                pattern=v["HPNAME"], scale=v["HPSCALE"], angle=v["HPANG"]))
        else:
            new = made.clone(loops=made.loops + loops,
                             loop_prims=made.loop_prims + loop_prims if loop_prims else made.loop_prims,
                             boundary_uids=made.boundary_uids + boundary_uids if boundary_uids else made.boundary_uids)
            c.replace(made, new)
            made = new


def REVCLOUD(c):
    arc = c.doc.vars.get("REVCLOUDARC", 10.0)
    a = yield pt("指定第一個角點或", kw=(("A", "弧長"),))
    if a == "A":
        v = yield num("指定弧長", default=arc)
        if isinstance(v, (int, float)) and v > 0:
            arc = c.doc.vars["REVCLOUDARC"] = float(v)
        a = yield pt("指定第一個角點")
    if not is_pt(a):
        return

    def mk(q):
        x0, y0, x1, y1 = min(a[0], q[0]), min(a[1], q[1]), max(a[0], q[0]), max(a[1], q[1])
        if x1 - x0 < G.EPS or y1 - y0 < G.EPS:
            return []
        cs = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        pts = []
        for i in range(4):
            s, t = cs[i], cs[(i + 1) % 4]
            n = max(1, int(round(G.dist(s, t) / arc)))
            for k in range(n):
                pts.append((s[0] + (t[0] - s[0]) * k / n, s[1] + (t[1] - s[1]) * k / n, -0.5))
        return [c.make(Polyline, pts=pts, closed=True)]

    b = yield pt("指定對角點", base=a, rubber=False, preview=mk)
    if is_pt(b):
        for e in mk(b):
            c.add(e)


# ================================================================ 修改
def ERASE(c):
    s = yield sel()
    if s:
        c.remove(s)
        c.msg("已刪除 %d 個物件。" % len(s))


def MOVE(c):
    s = yield sel()
    if not s:
        return
    b = yield pt("指定基準點")
    if not is_pt(b):
        return
    q = yield pt("指定第二點", base=b, preview=lambda q: _xform(s, G.m_translate(q[0] - b[0], q[1] - b[1])))
    if is_pt(q):
        dx,dy=q[0]-b[0],q[1]-b[1];m=G.m_translate(dx,dy); new=[]
        for e in s:
            n=e.transformed(m); brep=_solid_exact_transform(e,"MOVE",dx,dy)
            if brep is not None:n=n.clone(brep_b64=brep)
            new.append(n)
        c.replace_many(s,new)


def COPY(c):
    s = yield sel()
    if not s:
        return
    b = yield pt("指定基準點")
    if not is_pt(b):
        return
    made = []
    while True:
        q = yield pt("指定第二點或", base=b, kw=(("U", "退回"),) if made else (),
                     preview=lambda q: _copy_preview_xyz(s, b, q))
        if q == "U":
            if made:
                c.remove(made.pop())
            continue
        if not is_pt(q):
            return
        dx,dy=q[0]-b[0],q[1]-b[1];dz=(q[2] if len(q)>=3 else 0.0)-(b[2] if len(b)>=3 else 0.0);m=G.m_translate(dx,dy);new=[]
        for e in s:
            if isinstance(e,Solid3D):
                n=_translate_solid3d(e,dx,dy,dz)
            else:
                if abs(dz)>1e-12:c.msg("COPY：2D 圖元忽略 Z 位移；3D 實體已套用 XYZ 位移。")
                n=e.transformed(m);brep=_solid_exact_transform(e,"MOVE",dx,dy)
                if brep is not None:n=n.clone(brep_b64=brep)
            new.append(n)
        c.add_many(new)
        made.append(new)


def ROTATE(c):
    s = yield sel()
    if not s:
        return
    b = yield pt("指定基準點")
    if not is_pt(b):
        return
    copy = False
    ref = 0.0
    while True:
        a = yield pt("指定旋轉角度或", base=b, kw=(("C", "複製"), ("R", "參考")), number=True,
                     preview=lambda q: _xform(s, G.m_rotate(b, G.ang(b, q) - ref)))
        if a == "C":
            copy = True
            c.msg("旋轉選取物件的複本。")
            continue
        if a == "R":
            r = yield pt("指定參考角度", base=b, number=True, default=0.0)
            ref = G.ang(b, r) if is_pt(r) else (r if isinstance(r, (int, float)) else 0.0)
            continue
        break
    if a is None or isinstance(a, Kw):
        return
    a = (G.ang(b, a) if is_pt(a) else float(a)) - ref
    m=G.m_rotate(b,a);new=[]
    for e in s:
        n=e.transformed(m);brep=_solid_exact_transform(e,"ROTATE",b,a)
        if brep is not None:n=n.clone(brep_b64=brep)
        new.append(n)
    if copy:
        c.add_many(new)
    else:
        c.replace_many(s, new)


def SCALE(c):
    s = yield sel()
    if not s:
        return
    b = yield pt("指定基準點")
    if not is_pt(b):
        return
    copy = False
    ref = 1.0
    while True:
        f = yield pt("指定比例係數或", base=b, kw=(("C", "複製"), ("R", "參考")), number=True,
                     preview=lambda q: _xform(s, G.m_scale(b, max(G.dist(b, q) / ref, 1e-9))))
        if f == "C":
            copy = True
            c.msg("調整選取物件複本的比例。")
            continue
        if f == "R":
            r = yield pt("指定參考長度", number=True, default=1.0)
            if is_pt(r):
                r2 = yield pt("指定第二點", base=r)
                r = G.dist(r, r2) if is_pt(r2) else 1.0
            ref = float(r) if isinstance(r, (int, float)) and r > 0 else 1.0
            continue
        break
    if f is None or isinstance(f, Kw):
        return
    f = (G.dist(b, f) if is_pt(f) else float(f)) / ref
    if f <= 0:
        c.msg("比例係數必須大於 0。")
        return
    m=G.m_scale(b,f);new=[]
    for e in s:
        n=e.transformed(m);brep=_solid_exact_transform(e,"SCALE",b,f)
        if brep is not None:n=n.clone(brep_b64=brep)
        new.append(n)
    if copy:
        c.add_many(new)
    else:
        c.replace_many(s, new)


def MIRROR(c):
    s = yield sel()
    if not s:
        return
    a = yield pt("指定鏡射線的第一點")
    if not is_pt(a):
        return
    b = yield pt("指定鏡射線的第二點", base=a,
                 preview=lambda q: _xform(s, G.m_mirror(a, q)) if G.dist(a, q) > G.EPS else [])
    if not is_pt(b) or G.dist(a, b) < G.EPS:
        return
    k = yield kwd("是否刪除來源物件？", (("Y", "是"), ("N", "否")), default=Kw("N"))
    m=G.m_mirror(a,b);new=[]
    for e in s:
        n=e.transformed(m);brep=_solid_exact_transform(e,"MIRROR",a,b)
        if brep is not None:n=n.clone(brep_b64=brep)
        new.append(n)
    if k == "Y":
        c.replace_many(s, new)
    else:
        c.add_many(new)


def OFFSET(c):
    v = c.doc.vars
    d = yield num("指定偏移距離或", default=v["OFFSETDIST"], kw=(("T", "通過"),))
    through = d == "T"
    if not through:
        if not isinstance(d, (int, float)) or d <= 0:
            return
        v["OFFSETDIST"] = float(d)
    types = (Line, Circle, Arc, Polyline, Ellipse, Spline, XLine)
    while True:
        r = yield ent("選取要偏移的物件或 <結束>", types=types)
        if not is_pt(r):
            return
        e = r[0]

        def mk(q):
            dd = c.doc.hit_dist(e, q) if through else d
            o = E.offset_entity(e, dd, q) if dd > G.EPS else None
            return [o] if o else []

        q = yield pt("指定通過點" if through else "指定要偏移的那一側上的點", preview=mk)
        if not is_pt(q):
            return
        for o in mk(q):
            c.add(o)


def _trim_extend(c, trim):
    name = "修剪" if trim else "延伸"
    c.msg("目前的設定: 投影 = UCS, 邊 = 無；按住 Shift 可暫時切換修剪/延伸")
    edges = yield sel("選取%s邊，或按 Enter 全部選取" % ("切割" if trim else "邊界"))
    use_all = not edges
    history = []
    while True:
        r = yield ent("選取要%s的物件或" % name, kw=(("U", "退回"),))
        if r is None:
            return
        if r == "U":
            if history:
                olds, news = history.pop()
                c.replace_many(news, olds, exact=False)
            continue
        e, pk = r
        eds = [x for x in c.doc.entities if c.doc.visible(x)] if use_all else edges
        # AutoCAD 風格：TRIM 中按住 Shift 暫時 EXTEND；EXTEND 中按住 Shift 暫時 TRIM。
        do_trim = trim != bool(getattr(c, "entity_shift", False))
        if do_trim:
            res = E.trim_entity(c.doc, e, pk, eds)
        else:
            x = E.extend_entity(c.doc, e, pk, eds)
            res = [x] if x is not None else None
        if res is None:
            c.msg("物件未與%s邊相交。" % ("切割" if do_trim else "邊界"))
            continue
        c.replace(e, res)
        if not use_all:
            edges = [x for x in edges if x is not e] + (res if e in edges else [])
        history.append(([e], res))


def TRIM(c):
    yield from _trim_extend(c, True)


def EXTEND(c):
    yield from _trim_extend(c, False)


def FILLET(c):
    v = c.doc.vars
    multi = False
    while True:
        c.msg("目前的設定: 模式 = 修剪, 半徑 = %s" % fmt(v["FILLETRAD"]))
        r1 = yield ent("選取第一個物件或", kw=(("R", "半徑"), ("P", "聚合線"), ("M", "多重")))
        if r1 == "R":
            x = yield num("指定圓角半徑", default=v["FILLETRAD"])
            if isinstance(x, (int, float)) and x >= 0:
                v["FILLETRAD"] = float(x)
            continue
        if r1 == "M":
            multi = True
            continue
        if r1 == "P":
            rp = yield ent("選取 2D 聚合線", types=(Polyline,))
            if is_pt(rp):
                new, n = E.fillet_polyline(rp[0], r=v["FILLETRAD"])
                if n:
                    c.replace(rp[0], new)
                c.msg("%d 個轉角已做圓角。" % n)
            return
        if not is_pt(r1):
            return
        if not isinstance(r1[0], Line):
            c.msg("目前圓角只支援直線（聚合線請用 P 選項）。")
            continue
        r2 = yield ent("選取第二個物件")
        if not is_pt(r2) or r2[0] is r1[0]:
            return
        if not isinstance(r2[0],Line):
            c.msg("目前圓角只支援直線對直線；弧/圓與直線的圓角將在後續幾何核心加入。")
            if not multi:return
            continue
        res = E.fillet_lines(r1[0], r1[1], r2[0], r2[1], v["FILLETRAD"])
        if res is None:
            c.msg("無法做圓角：線平行或半徑太大。")
        else:
            c.replace(r1[0], res[0])
            c.replace(r2[0], [res[1]] + ([res[2].clone(**c.doc.new_props())] if res[2] is not None else []))
        if not multi:
            return


def CHAMFER(c):
    v = c.doc.vars
    while True:
        c.msg("(修剪模式) 目前的倒角距離1 = %s, 距離2 = %s" % (fmt(v["CHAMFERA"]), fmt(v["CHAMFERB"])))
        r1 = yield ent("選取第一條線或", kw=(("D", "距離"), ("P", "聚合線")))
        if r1 == "D":
            a = yield num("指定第一個倒角距離", default=v["CHAMFERA"])
            if isinstance(a, (int, float)) and a >= 0:
                v["CHAMFERA"] = float(a)
            b = yield num("指定第二個倒角距離", default=v["CHAMFERA"])
            if isinstance(b, (int, float)) and b >= 0:
                v["CHAMFERB"] = float(b)
            continue
        if r1 == "P":
            rp = yield ent("選取 2D 聚合線", types=(Polyline,))
            if is_pt(rp):
                new, n = E.fillet_polyline(rp[0], d1=v["CHAMFERA"], d2=v["CHAMFERB"])
                if n:
                    c.replace(rp[0], new)
                c.msg("%d 個轉角已做倒角。" % n)
            return
        if not is_pt(r1):
            return
        if not isinstance(r1[0], Line):
            c.msg("倒角只支援直線（聚合線請用 P 選項）。")
            continue
        r2 = yield ent("選取第二條線")
        if not is_pt(r2) or r2[0] is r1[0]:
            return
        if not isinstance(r2[0],Line):
            c.msg("目前倒角只支援直線對直線；不再靜默忽略弧或圓。")
            continue
        res = E.chamfer_lines(r1[0], r1[1], r2[0], r2[1], v["CHAMFERA"], v["CHAMFERB"])
        if res is None:
            c.msg("無法做倒角：線平行或距離太大。")
        else:
            c.replace(r1[0], res[0])
            c.replace(r2[0], [res[1]] + ([res[2]] if res[2] is not None else []))
        return


def STRETCH(c):
    c.msg("以框選窗（由右往左）選取要拉伸的物件...")
    s = yield sel()
    if not s:
        return
    rect = c.last_window
    b = yield pt("指定基準點")
    if not is_pt(b):
        return

    def do(q):
        dx, dy = q[0] - b[0], q[1] - b[1]
        if rect is None:
            return [e.transformed(G.m_translate(dx, dy)) for e in s]
        return [E.stretch_entity(e, rect, dx, dy) for e in s]

    q = yield pt("指定第二點", base=b, preview=lambda q: do(q)[:400])
    if is_pt(q):
        c.replace_many(s, do(q))


ARRAY_ITEM_SOFT_LIMIT = 10000
ARRAY_ITEM_HARD_LIMIT = 100000

def _array_source_count(src, limit=ARRAY_ITEM_HARD_LIMIT):
    total=0
    for e in src or []:
        if isinstance(e,Array):
            try:n=e.expanded_count(limit=max(1,limit-total))
            except Exception:n=limit+1
        else:n=1
        total+=n
        if total>limit:return total
    return total

def _array_count_ok(c, n):
    n = int(n)
    if n > ARRAY_ITEM_HARD_LIMIT:
        c.msg("陣列項目數 %d 超過安全上限 %d；已取消，避免介面卡死。" % (n, ARRAY_ITEM_HARD_LIMIT))
        return False
    if n > ARRAY_ITEM_SOFT_LIMIT:
        c.msg("陣列項目數 %d 很大；為維持互動效能，請縮小到 %d 以下或分批建立。" % (n, ARRAY_ITEM_SOFT_LIMIT))
        return False
    return True

def ARRAY(c):
    s = yield sel()
    if not s:
        return
    k = yield kwd("輸入陣列類型", (("R", "矩形"), ("PO", "環形")), default=Kw("R"))
    if k == "PO":
        yield from _array_polar(c, s)
    else:
        yield from _array_rect(c, s)


def _array_rect(c, s):
    rows = yield num("輸入列數", default=3)
    cols = yield num("輸入欄數", default=4)
    if not all(isinstance(x, (int, float)) for x in (rows, cols)):
        return
    rows, cols = max(1, int(rows)), max(1, int(cols))
    total=rows*cols*_array_source_count(s)
    if not _array_count_ok(c,total):
        c.msg("巢狀陣列展開總數將達 %d；已取消。"%total)
        return
    b = c.doc.extents(s) or (0, 0, 10, 10)
    dy = yield num("指定列間距", default=round((b[3] - b[1]) * 1.5, 4) or 10.0)
    dx = yield num("指定欄間距", default=round((b[2] - b[0]) * 1.5, 4) or 10.0)
    if not all(isinstance(x, (int, float)) for x in (dx, dy)):
        return
    # 關聯式陣列：來源幾何與參數保留在單一 Array 圖元內。
    c.remove(s)
    arr = c.make(Array, source=list(s), mode="RECT", rows=rows, cols=cols, dx=float(dx), dy=float(dy),
                 col_vec=(float(dx), 0.0), row_vec=(0.0, float(dy)))
    c.add(arr)
    c.keep_selection([arr])
    c.msg("已建立 %d x %d 關聯式矩形陣列；可用 ARRAYEDIT 修改參數。" % (rows, cols))


def _array_polar(c, s):
    cen = yield pt("指定陣列的中心點")
    if not is_pt(cen):
        return
    n = yield num("輸入項目數", default=6)
    if not isinstance(n, (int, float)) or int(n) < 2:
        return
    n = int(n)
    total=n*_array_source_count(s)
    if not _array_count_ok(c,total):
        c.msg("巢狀陣列展開總數將達 %d；已取消。"%total)
        return
    fill = yield num("指定填滿角度 (+=逆時針, -=順時針)", default=360.0)
    if not isinstance(fill, (int, float)) or abs(fill) < G.EPS:
        return
    rot = yield kwd("陣列時旋轉項目？", (("Y", "是"), ("N", "否")), default=Kw("Y"))
    step = fill / n if abs(abs(fill) - 360.0) < 1e-9 else fill / (n - 1)
    c.remove(s)
    arr = c.make(Array, source=list(s), mode="POLAR", cx=cen[0], cy=cen[1], count=n, fill=float(fill), rotate_items=(rot == "Y"))
    c.add(arr)
    c.keep_selection([arr])
    c.msg("已建立 %d 個項目的關聯式環形陣列；可用 ARRAYEDIT 修改參數。" % n)


def ARRAYRECT(c):
    s = yield sel()
    if s:
        yield from _array_rect(c, s)


def ARRAYPOLAR(c):
    s = yield sel()
    if s:
        yield from _array_polar(c, s)


def ARRAYEDIT(c):
    r = yield ent("選取關聯式陣列", types=(Array,))
    if not is_pt(r):
        return
    e = r[0]
    if e.mode.upper() == "POLAR":
        n = yield num("輸入項目數", default=e.count)
        if not isinstance(n, (int, float)) or int(n) < 1 or not _array_count_ok(c, int(n)):
            return
        fill = yield num("指定填滿角度", default=e.fill)
        if not isinstance(fill, (int, float)) or abs(fill) < G.EPS:
            return
        rot = yield kwd("陣列時旋轉項目？", (("Y", "是"), ("N", "否")), default=Kw("Y" if e.rotate_items else "N"))
        c.replace(e, e.clone(count=int(n), fill=float(fill), rotate_items=(rot == "Y")))
    else:
        rows = yield num("輸入列數", default=e.rows)
        cols = yield num("輸入欄數", default=e.cols)
        dy = yield num("指定列間距", default=e.dy)
        dx = yield num("指定欄間距", default=e.dx)
        if not all(isinstance(x, (int, float)) for x in (rows, cols, dx, dy)):
            return
        rows, cols = max(1, int(rows)), max(1, int(cols))
        if not _array_count_ok(c, rows * cols):
            return
        # ARRAYEDIT dimensions are entered in the array's current local row/column directions.
        cv = e.col_vec if any(abs(float(v)) > G.EPS for v in e.col_vec) else (e.dx, 0.0)
        rv = e.row_vec if any(abs(float(v)) > G.EPS for v in e.row_vec) else (0.0, e.dy)
        cvL, rvL = math.hypot(*cv), math.hypot(*rv)
        cv2 = (cv[0]*float(dx)/cvL, cv[1]*float(dx)/cvL) if cvL > G.EPS else (float(dx),0.0)
        rv2 = (rv[0]*float(dy)/rvL, rv[1]*float(dy)/rvL) if rvL > G.EPS else (0.0,float(dy))
        c.replace(e, e.clone(rows=rows, cols=cols, dx=abs(float(dx)), dy=abs(float(dy)), col_vec=cv2, row_vec=rv2))
    c.msg("關聯式陣列參數已更新。")

def EXPLODE(c):
    s = yield sel()
    n = 0
    for e in s or []:
        res = E.explode_entity(c.doc, e)
        if res:
            c.replace(e, res)
            n += 1
    if s:
        c.msg("已分解 %d 個物件。" % n)


def JOIN(c):
    s = yield sel("選取要接合的物件")
    if not s:
        return
    new, used = E.join_entities(s)
    if not new:
        c.msg("沒有端點相接的物件可以接合。")
        return
    c.remove(used)
    c.add_many(new)
    c.msg("%d 個物件已接合成 %d 條聚合線。" % (len(used), len(new)))


def BREAK(c):
    r = yield ent("選取物件", types=(Line, Arc, Circle, Polyline, Ellipse, Spline, XLine))
    if not is_pt(r):
        return
    e, p1 = r
    prims, closed = E.path_of(e)
    p2 = yield pt("指定第二個切斷點或", kw=(("F", "第一點"),))
    if p2 == "F":
        p1 = yield pt("指定第一個切斷點")
        if not is_pt(p1):
            return
        p2 = yield pt("指定第二個切斷點")
    if not is_pt(p2):
        return
    s1, s2 = E.path_station(prims, p1), E.path_station(prims, p2)
    if closed:
        res = E.cut_out(e, s1, s2 if s2 > s1 else s2 + E.path_len(prims))
    else:
        lo, hi = min(s1, s2), max(s1, s2)
        res = E.cut_out(e, lo, hi)
    c.replace(e, res)


def MATCHPROP(c):
    r = yield ent("選取來源物件")
    if not is_pt(r):
        return
    src = r[0]
    while True:
        s = yield sel("選取目標物件")
        if not s:
            return
        c.replace_many(s, [e.clone(layer=src.layer, color=src.color, ltype=src.ltype, lw=src.lw, lts=src.lts)
                           for e in s])


def DIVIDE(c, measure=False):
    r = yield ent("選取要%s的物件" % ("等距" if measure else "等分"), types=(Line, Arc, Circle, Polyline, Ellipse, Spline))
    if not is_pt(r):
        return
    prims, closed = E.path_of(r[0])
    total = E.path_len(prims)
    if measure:
        d = yield num("指定分段長度")
        if not isinstance(d, (int, float)) or d <= 0:
            return
        sts = [d * i for i in range(1, int(total / d + 1e-9) + 1) if d * i < total - 1e-9 or closed]
    else:
        n = yield num("輸入分段數目")
        if not isinstance(n, (int, float)) or int(n) < 2:
            return
        n = int(n)
        sts = [total * i / n for i in range(0 if closed else 1, n)]
    for s in sts:
        q = E.path_point(prims, s)
        c.add(c.make(Point, x=q[0], y=q[1]))
    c.msg("已放置 %d 個點（物件鎖點請開啟「節點」）。" % len(sts))


def MEASURE(c):
    yield from DIVIDE(c, measure=True)


def OVERKILL(c):
    s = yield sel()
    if not s:
        return
    seen, dup = set(), []
    for e in s:
        d = e.to_dict()
        key = repr(sorted((k, repr(v)) for k, v in d.items()))
        if isinstance(e, Line):
            a, b = sorted([(round(e.x1, 8), round(e.y1, 8)), (round(e.x2, 8), round(e.y2, 8))])
            key = ("LINE", e.layer, a, b)
        if key in seen:
            dup.append(e)
        seen.add(key)
    if dup:
        c.remove(dup)
    c.msg("已刪除 %d 個重複物件。" % len(dup))


# ================================================================ 標註
def _dim_kw(c):
    s = c.doc.vars.get("DIMSCALE", 1.0)
    return dict(th=c.doc.vars["DIMTXT"] * s, asz=c.doc.vars["DIMASZ"] * s, dec=int(c.doc.vars["DIMDEC"]))


def _auto_rot(p1, p2, loc):
    x0, x1 = min(p1[0], p2[0]), max(p1[0], p2[0])
    y0, y1 = min(p1[1], p2[1]), max(p1[1], p2[1])
    ox = max(x0 - loc[0], loc[0] - x1, 0.0)
    oy = max(y0 - loc[1], loc[1] - y1, 0.0)
    if abs(x1 - x0) < G.EPS:
        return 90.0
    if abs(y1 - y0) < G.EPS:
        return 0.0
    if ox > oy:
        return 90.0
    if oy > ox:
        return 0.0
    return 0.0 if (x1 - x0) >= (y1 - y0) else 90.0


def _seg_at(c, e, pk):
    """回傳圖元上最接近 pk 的那一段 prim。"""
    best = None
    for pr in c.doc.prims(e):
        d = G.nearest_on_prim(pk, pr)[0]
        if best is None or d < best[0]:
            best = (d, pr)
    return best[1] if best else None


def _two_points(c, first_prompt="指定第一條延伸線原點或 <選取物件>"):
    p1 = yield pt(first_prompt)
    if p1 is None:
        r = yield ent("選取要標註的物件")
        if not is_pt(r):
            return None
        pr = _seg_at(c, r[0], r[1])
        if pr is None:
            return None
        if pr[0] == 'L':
            return (pr[1], pr[2]), (pr[3], pr[4])
        return G.arc_pts(pr)
    if not is_pt(p1):
        return None
    p2 = yield pt("指定第二條延伸線原點", base=p1)
    if not is_pt(p2):
        return None
    return p1, p2


def DIMLINEAR(c):
    r = yield from _two_points(c)
    if not r:
        return
    p1, p2 = r
    force = [None]
    while True:
        mk = lambda q: c.make(Dim, kind="LIN", pts=[p1, p2, q],
                              rot=force[0] if force[0] is not None else _auto_rot(p1, p2, q), **_dim_kw(c))
        q = yield pt("指定標註線位置或", kw=(("H", "水平"), ("V", "垂直"), ("T", "文字")), preview=lambda q: [mk(q)])
        if q == "H":
            force[0] = 0.0
        elif q == "V":
            force[0] = 90.0
        elif q == "T":
            s = yield txt("輸入標註文字 <量測值>")
            force.append(s or "")
        else:
            break
    if is_pt(q):
        d = mk(q)
        if len(force) > 1 and force[-1]:
            d = d.clone(text=force[-1])
        c.add(d)
        c.msg("標註文字 = %s" % d.label())


def DIMALIGNED(c):
    r = yield from _two_points(c)
    if not r:
        return
    p1, p2 = r
    mk = lambda q: c.make(Dim, kind="ALI", pts=[p1, p2, q], **_dim_kw(c))
    q = yield pt("指定標註線位置", preview=lambda q: [mk(q)])
    if is_pt(q):
        d = c.add(mk(q))
        c.msg("標註文字 = %s" % d.label())


def _dim_radial(c, kind):
    r = yield ent("選取弧或圓", types=(Circle, Arc, Polyline))
    if not is_pt(r):
        return
    pr = _seg_at(c, r[0], r[1])
    if pr is None or pr[0] != 'A':
        c.msg("選取的物件不是弧或圓。")
        return
    cen, rad = (pr[1], pr[2]), pr[3]

    def mk(q):
        a = G.ang(cen, q) if G.dist(cen, q) > G.EPS else 0.0
        return c.make(Dim, kind=kind, pts=[cen, G.polar(cen, a, rad), q], **_dim_kw(c))

    q = yield pt("指定標註線位置", preview=lambda q: [mk(q)])
    if is_pt(q):
        d = c.add(mk(q))
        c.msg("標註文字 = %s" % d.label())


def DIMRADIUS(c):
    yield from _dim_radial(c, "RAD")


def DIMDIAMETER(c):
    yield from _dim_radial(c, "DIA")


def DIMANGULAR(c):
    r1 = yield ent("選取第一條線", types=(Line, Polyline))
    if not is_pt(r1):
        return
    r2 = yield ent("選取第二條線", types=(Line, Polyline))
    if not is_pt(r2):
        return
    a, b = _seg_at(c, r1[0], r1[1]), _seg_at(c, r2[0], r2[1])
    if a is None or b is None or a[0] != 'L' or b[0] != 'L':
        c.msg("請選取兩條直線段。")
        return
    ips = G.intersect(a, b, True, True)
    if not ips:
        c.msg("兩線平行。")
        return
    v = ips[0]
    far = lambda pr: max(((pr[1], pr[2]), (pr[3], pr[4])), key=lambda p: G.dist(p, v))
    pa, pb = far(a), far(b)

    def mk(q):
        # 依游標所在的象限決定標哪一個角
        qa = pa if (q[0] - v[0]) * (pa[0] - v[0]) + (q[1] - v[1]) * (pa[1] - v[1]) >= 0 else \
            (2 * v[0] - pa[0], 2 * v[1] - pa[1])
        qb = pb if (q[0] - v[0]) * (pb[0] - v[0]) + (q[1] - v[1]) * (pb[1] - v[1]) >= 0 else \
            (2 * v[0] - pb[0], 2 * v[1] - pb[1])
        return c.make(Dim, kind="ANG", pts=[v, qa, qb, q], **_dim_kw(c))

    q = yield pt("指定標註弧線位置", preview=lambda q: [mk(q)] if G.dist(q, v) > G.EPS else [])
    if is_pt(q):
        d = c.add(mk(q))
        c.msg("標註文字 = %s" % d.label())


def DIM(c):
    """智慧標註：依選到的物件自動決定標註類型。"""
    while True:
        r = yield Req("entity", "選取物件或指定第一條延伸線原點或", (("A", "角度"), ("U", "退回")), default="point")
        if r is None:
            return
        if r == "A":
            yield from DIMANGULAR(c)
            continue
        if r == "U":
            c.undo_last_add()
            continue
        if is_pt(r) and r[0] is None:            # 點在空白處：當成第一個原點
            p1 = r[1]
            p2 = yield pt("指定第二條延伸線原點", base=p1)
            if not is_pt(p2):
                return
            yield from _dim_place(c, p1, p2)
            continue
        e, pk = r
        pr = _seg_at(c, e, pk)
        if pr is None:
            continue
        if pr[0] == 'A':
            cen, rad = (pr[1], pr[2]), pr[3]
            kind = "DIA" if pr[5] >= 360.0 - 1e-6 else "RAD"
            mk = lambda q: c.make(Dim, kind=kind, pts=[cen, G.polar(cen, G.ang(cen, q), rad), q], **_dim_kw(c))
            q = yield pt("指定%s標註位置" % ("直徑" if kind == "DIA" else "半徑"),
                         preview=lambda q: [mk(q)] if G.dist(cen, q) > G.EPS else [])
            if is_pt(q):
                c.add(mk(q))
        else:
            yield from _dim_place(c, (pr[1], pr[2]), (pr[3], pr[4]))


def _dim_place(c, p1, p2):
    def mk(q):
        x0, x1 = min(p1[0], p2[0]), max(p1[0], p2[0])
        y0, y1 = min(p1[1], p2[1]), max(p1[1], p2[1])
        oblique = abs(x1 - x0) > 1e-9 and abs(y1 - y0) > 1e-9
        inx, iny = x0 <= q[0] <= x1, y0 <= q[1] <= y1
        if oblique and (inx == iny):
            return c.make(Dim, kind="ALI", pts=[p1, p2, q], **_dim_kw(c))
        return c.make(Dim, kind="LIN", pts=[p1, p2, q], rot=_auto_rot(p1, p2, q), **_dim_kw(c))

    q = yield pt("指定標註線位置", preview=lambda q: [mk(q)])
    if is_pt(q):
        d = c.add(mk(q))
        c.msg("標註文字 = %s" % d.label())


def MLEADER(c):
    a = yield pt("指定引線箭頭位置")
    if not is_pt(a):
        return
    b = yield pt("指定引線連字線位置", base=a,
                 preview=lambda q: [c.make(Dim, kind="LDR", pts=[a, q], text="", **_dim_kw(c))])
    if not is_pt(b):
        return
    if c.ui:
        s = c.ui.ask_text("引線文字", "")
    else:
        s = yield txt("輸入引線文字")
    c.add(c.make(Dim, kind="LDR", pts=[a, b], text=(s or "").replace("\\P", "\n"), **_dim_kw(c)))


# ================================================================ 圖塊
def BLOCK(c):
    name = yield txt("輸入圖塊名稱")
    if not name:
        return
    name = name.strip()
    if name in c.doc.blocks:
        k = yield kwd("圖塊「%s」已存在，要重新定義嗎？" % name, (("Y", "是"), ("N", "否")), default=Kw("N"))
        if k != "Y":
            return
    b = yield pt("指定插入基準點")
    if not is_pt(b):
        return
    s = yield sel()
    if not s:
        return
    c.touch()
    c.doc.blocks[name] = Block(name, b[0], b[1], list(s))
    c.doc.block_rev += 1
    c.remove(s)
    c.add(c.make(Insert, name=name, x=b[0], y=b[1]))
    c.doc.vars["INSNAME"] = name
    c.msg("圖塊「%s」已建立，含 %d 個物件。" % (name, len(s)))


def INSERT(c):
    names = sorted(n for n in c.doc.blocks if not n.startswith("*"))
    if not names:
        c.msg("這張圖沒有圖塊定義。請先用 BLOCK 建立。")
        return
    last = c.doc.vars.get("INSNAME") if c.doc.vars.get("INSNAME") in c.doc.blocks else names[0]
    if c.ui:
        name = c.ui.ask_choice("插入圖塊", "圖塊名稱:", names, last)
    else:
        name = yield txt("輸入圖塊名稱", default=last)
    if not name:
        return
    if name not in c.doc.blocks:
        c.msg("找不到圖塊「%s」。" % name)
        return
    c.doc.vars["INSNAME"] = name
    scale, rot = 1.0, 0.0
    while True:
        p = yield pt("指定插入點或", kw=(("S", "比例"), ("R", "旋轉")),
                     preview=lambda q: [c.make(Insert, name=name, x=q[0], y=q[1], sx=scale, sy=scale, rot=rot)])
        if p == "S":
            v = yield num("指定比例係數", default=scale)
            if isinstance(v, (int, float)) and v > 0:
                scale = float(v)
        elif p == "R":
            v = yield num("指定旋轉角度", default=rot)
            if isinstance(v, (int, float)):
                rot = float(v)
        else:
            break
    if is_pt(p):
        c.add(c.make(Insert, name=name, x=p[0], y=p[1], sx=scale, sy=scale, rot=rot))


# ================================================================ 查詢
def DIST(c):
    a = yield pt("指定第一點")
    if not is_pt(a):
        return
    b = yield pt("指定第二點", base=a)
    if not is_pt(b):
        return
    p = c.doc.vars.get("LUPREC", 4)
    c.msg("距離 = %s，XY 平面內角度 = %s°" % (fmt(G.dist(a, b), p), fmt(G.ang(a, b), 2)))
    c.msg("X 差值 = %s，Y 差值 = %s" % (fmt(b[0] - a[0], p), fmt(b[1] - a[1], p)))


def AREA(c):
    p = yield pt("指定第一個角點或", kw=(("O", "物件"),))
    pr = c.doc.vars.get("LUPREC", 4)
    if p == "O":
        r = yield ent("選取物件")
        if not is_pt(r):
            return
        e = r[0]
        if isinstance(e, Circle):
            c.msg("面積 = %s，圓周 = %s" % (fmt(math.pi * e.r ** 2, pr), fmt(TWO_PI * e.r, pr)))
        elif isinstance(e, Polyline):
            c.msg("面積 = %s，%s = %s" % (fmt(e.area(), pr), "周長" if e.closed else "長度", fmt(e.length(), pr)))
        elif isinstance(e, Ellipse):
            a = math.hypot(e.mx, e.my)
            c.msg("面積 = %s" % fmt(math.pi * a * a * e.ratio, pr))
        elif isinstance(e, Hatch):
            c.msg("面積 = %s" % fmt(e.area(), pr))
        else:
            c.msg("選取的物件沒有面積。")
        return
    if not is_pt(p):
        return
    pts = [p]
    while True:
        q = yield pt("指定下一點或 <總計>", base=pts[-1], rubber=True,
                     preview=lambda q: [c.make(Polyline, pts=[x + (0.0,) for x in pts + [q]], closed=True)])
        if not is_pt(q):
            break
        pts.append(q)
    if len(pts) >= 3:
        per = sum(G.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))
        c.msg("面積 = %s，周長 = %s" % (fmt(abs(G.poly_area(pts)), pr), fmt(per, pr)))


def ID(c):
    p = yield pt("指定點")
    if is_pt(p):
        c.msg("X = %s     Y = %s     Z = 0" % (fmt(p[0], 4), fmt(p[1], 4)))


def LIST(c):
    s = yield sel()
    pr = c.doc.vars.get("LUPREC", 4)
    f = lambda v: fmt(v, pr)
    for e in (s or [])[:30]:
        c.msg("  %s    圖層: \"%s\"   顏色: %s   線型: %s" % (e.NAME, e.layer, color_name(e.color), e.ltype))
        if isinstance(e, Line):
            c.msg("      自 點 X=%s Y=%s  至 點 X=%s Y=%s  長度=%s  角度=%s" %
                  (f(e.x1), f(e.y1), f(e.x2), f(e.y2), f(e.length()), fmt(G.ang((e.x1, e.y1), (e.x2, e.y2)), 2)))
        elif isinstance(e, Circle):
            c.msg("      中心點 X=%s Y=%s  半徑=%s  圓周=%s  面積=%s" %
                  (f(e.cx), f(e.cy), f(e.r), f(TWO_PI * e.r), f(math.pi * e.r ** 2)))
        elif isinstance(e, Arc):
            c.msg("      中心點 X=%s Y=%s  半徑=%s  起始角=%s  終止角=%s  長度=%s" %
                  (f(e.cx), f(e.cy), f(e.r), fmt(e.a0, 2), fmt(e.a1, 2), f(e.length())))
        elif isinstance(e, Polyline):
            c.msg("      %s  頂點數=%d  長度=%s  面積=%s" % ("閉合" if e.closed else "開放", len(e.pts), f(e.length()),
                                                    f(e.area())))
        elif isinstance(e, (Text, MText)):
            c.msg("      插入點 X=%s Y=%s  高度=%s  文字=%s" % (f(e.x), f(e.y), f(e.height), e.text.replace("\n", "\\P")))
        elif isinstance(e, Insert):
            c.msg("      圖塊名稱=%s  插入點 X=%s Y=%s  比例=%s  旋轉=%s" % (e.name, f(e.x), f(e.y), f(e.sx), fmt(e.rot, 2)))
        elif isinstance(e, Dim):
            c.msg("      標註類型=%s  文字=%s" % (e.kind, e.label()))
        elif isinstance(e, Solid3D):
            b=e.bbox3d()
            if b:
                try:
                    from .io_utils import _cq_shape_from_solid
                    vol=float(_cq_shape_from_solid(e,1.0).Volume())
                except Exception:
                    vol=0.0
                c.msg("      類型=%s  尺寸 X=%s Y=%s Z=%s  體積=%s  頂點=%d  面=%d  BREP=%s" %
                      (e.shape,f(b[3]-b[0]),f(b[4]-b[1]),f(b[5]-b[2]),f(vol),len(e.vertices),len(e.faces),
                       "是" if bool(getattr(e,"brep_b64","")) else "否"))
    if s and len(s) > 30:
        c.msg("  ...（共 %d 個物件，只列出前 30 個）" % len(s))


# ================================================================ 檢視
def ZOOM(c):
    p = yield pt("指定窗選角點，輸入比例係數 (nX)，或", number=True,
                 kw=(("A", "全部"), ("E", "實際範圍"), ("P", "上一個"), ("W", "視窗"), ("O", "物件")))
    if p in ("A", "E"):
        c.zoom_extents()
    elif p == "P":
        c.zoom_prev()
    elif p == "O":
        s = yield sel()
        if s:
            b = c.doc.extents(s)
            if b:
                c.zoom_rect((b[0], b[1]), (b[2], b[3]))
    elif isinstance(p, (int, float)) and not isinstance(p, bool):
        if p > 0:
            c.zoom_factor(float(p))
    else:
        if p == "W":
            p = yield pt("指定第一個角點")
        if is_pt(p):
            q = yield pt("指定對角點", base=p, rubber=False,
                         preview=lambda q: [Polyline(pts=_rect_pts(p, q), closed=True, color=7)])
            if is_pt(q):
                c.zoom_rect(p, q)


def REGEN(c):
    c.regen()
    c.msg("重生模型。")
    return
    yield


def PAN(c):
    c.msg("按住滑鼠中鍵（滾輪）拖曳即可平移。")
    return
    yield


# ================================================================ 圖層工具
def _layer_pick(c, prompt, fn, done):
    n = 0
    while True:
        r = yield ent(prompt)
        if not is_pt(r):
            break
        c.touch()
        if fn(c.doc.layer(r[0].layer)) is not False:
            n += 1
        c.changed()
    return n


def LAYOFF(c):
    def f(ly):
        if ly.name == c.doc.current_layer:
            c.msg("圖層「%s」是目前圖層，仍然將它關閉。" % ly.name)
        ly.on = False
        c.msg("圖層「%s」已關閉。" % ly.name)
    yield from _layer_pick(c, "選取要關閉之圖層上的物件", f, None)


def LAYFRZ(c):
    def f(ly):
        if ly.name == c.doc.current_layer:
            c.msg("無法凍結目前圖層「%s」。" % ly.name)
            return False
        ly.frozen = True
        c.msg("圖層「%s」已凍結。" % ly.name)
    yield from _layer_pick(c, "選取要凍結之圖層上的物件", f, None)


def LAYLCK(c):
    def f(ly):
        ly.locked = True
        c.msg("圖層「%s」已鎖護。" % ly.name)
    yield from _layer_pick(c, "選取要鎖護之圖層上的物件", f, None)


def LAYON(c):
    c.touch()
    for ly in c.doc.layers.values():
        ly.on = True
    c.changed()
    c.msg("所有圖層皆已打開。")
    return
    yield


def LAYTHW(c):
    c.touch()
    for ly in c.doc.layers.values():
        ly.frozen = False
    c.changed()
    c.msg("所有圖層皆已解凍。")
    return
    yield


def LAYULK(c):
    c.touch()
    for ly in c.doc.layers.values():
        ly.locked = False
    c.changed()
    c.msg("所有圖層皆已解鎖。")
    return
    yield


def LAYMCUR(c):
    r = yield ent("選取其圖層將成為目前圖層的物件")
    if is_pt(r):
        c.touch()
        c.doc.current_layer = r[0].layer
        c.changed()
        c.msg("「%s」現在是目前的圖層。" % r[0].layer)


def LAYISO(c):
    s = yield sel("選取要隔離之圖層上的物件")
    if not s:
        return
    keep = {e.layer for e in s}
    c.touch()
    c.doc.vars["_LAYISO"] = {n: ly.on for n, ly in c.doc.layers.items()}
    for n, ly in c.doc.layers.items():
        ly.on = n in keep
    if c.doc.current_layer not in keep:
        c.doc.current_layer = sorted(keep)[0]
    c.changed()
    c.msg("已隔離 %d 個圖層。用 LAYUNISO 還原。" % len(keep))


def LAYUNISO(c):
    st = c.doc.vars.pop("_LAYISO", None)
    if not st:
        c.msg("沒有可還原的圖層隔離狀態。")
    else:
        c.touch()
        for n, on in st.items():
            if n in c.doc.layers:
                c.doc.layers[n].on = on
        c.changed()
        c.msg("已還原圖層隔離前的狀態。")
    return
    yield


def SELECTSIMILAR(c):
    s = yield sel()
    if not s:
        return
    keys = {(type(e), e.layer) for e in s}
    c.keep_selection([e for e in c.doc.entities if (type(e), e.layer) in keys and c.doc.editable(e)])


def PURGE(c):
    used = set()

    def walk(ents):
        for e in ents:
            used.add(("L", e.layer))
            if isinstance(e, Insert) and ("B", e.name) not in used:
                used.add(("B", e.name))
                b = c.doc.blocks.get(e.name)
                if b:
                    walk(b.entities)

    walk(c.doc.entities)
    lay = [n for n in c.doc.layers if ("L", n) not in used and n not in ("0", c.doc.current_layer)]
    blk = [n for n in c.doc.blocks if ("B", n) not in used]
    if lay or blk:
        c.touch()
        for n in lay:
            del c.doc.layers[n]
        for n in blk:
            del c.doc.blocks[n]
        c.doc.block_rev += 1
        c.changed()
    c.msg("已清除 %d 個未使用的圖層、%d 個未使用的圖塊。" % (len(lay), len(blk)))
    return
    yield


def SETVAR(c, name):
    cur = c.doc.vars[name]
    if isinstance(cur, str):
        v = yield txt("輸入 %s 的新值 <%s>" % (name, cur))
        if v:
            c.touch()
            c.doc.vars[name] = v.strip()
    else:
        v = yield num("輸入 %s 的新值" % name, default=cur)
        if isinstance(v, (int, float)):
            c.touch()
            c.doc.vars[name] = int(v) if isinstance(cur, int) else float(v)
    c.changed()


def GRIP_STRETCH(c, e, i):
    base = e.grips()[i]
    q = yield pt("** 拉伸 ** 指定拉伸點", base=base, preview=lambda q: [e.grip_moved(i, q)])
    if is_pt(q):
        new = e.grip_moved(i, q)
        c.replace(e, new)
        c.keep_selection([new if x is e else x for x in c.grip_selection])


def PASTECLIP(c, ents, base):
    if not ents:
        c.msg("剪貼簿是空的。")
        return
    q = yield pt("指定插入點", preview=lambda q: _xform(ents, G.m_translate(q[0] - base[0], q[1] - base[1])))
    if is_pt(q):
        dx=q[0]-base[0];dy=q[1]-base[1];dz=(q[2] if len(q)>=3 else 0.0)-(base[2] if len(base)>=3 else 0.0);m=G.m_translate(dx,dy)
        c.add_many([_translate_solid3d(e,dx,dy,dz) if isinstance(e,Solid3D) else e.transformed(m) for e in ents])


# ================================================================ 3D 基礎（v0.6）
def _solid(c, vertices, edges, faces=(), shape="CUSTOM"):
    return Solid3D(vertices=[tuple(map(float, v)) for v in vertices],
                   edges=[tuple(map(int, e)) for e in edges],
                   faces=[list(map(int, f)) for f in faces],
                   shape=shape, **c.doc.new_props())


def _point_distance(a, b):
    """Distance for command points; honours Z when both inputs are true XYZ points."""
    if isinstance(a, tuple) and isinstance(b, tuple) and len(a) >= 3 and len(b) >= 3:
        dx=float(a[0])-float(b[0]); dy=float(a[1])-float(b[1]); dz=float(a[2])-float(b[2])
        return math.sqrt(dx*dx+dy*dy+dz*dz)
    return G.dist(a,b)


def _prefer_exact(c, fallback, shape, name):
    """Attach exact OpenCascade geometry without replacing a clean native display mesh.

    Basic primitives already have compact, predictable display meshes.  Re-tessellating
    them through OCC made smooth primitives such as SPHERE depend on CadQuery's default
    angular limits and also produced unnecessarily dense wireframes.  The exact BREP is
    authoritative for STEP/boolean operations; the native mesh remains the fast display
    cache.
    """
    try:
        from .io_utils import _shape_to_brep_b64
        fallback.brep_b64=_shape_to_brep_b64(shape)
        return fallback
    except Exception:
        try:
            exact=_cq_to_solid(c, shape, name, deflection=0.45)
            return exact or fallback
        except Exception:
            return fallback

def _cq_polyhedron(vertices, faces):
    """Build an exact planar-faced OpenCascade solid from indexed polygons."""
    import cadquery as cq
    ff=[]
    for face in faces:
        pts=[cq.Vector(*map(float,vertices[int(i)])) for i in face]
        if len(pts)<3:continue
        wire=cq.Wire.makePolygon(pts,close=True)
        ff.append(cq.Face.makeFromWires(wire))
    if not ff:return None
    shell=cq.Shell.makeShell(ff)
    solid=cq.Solid.makeSolid(shell)
    return solid if solid.isValid() else shell

def _cq_profile(e):
    """Build an exact CadQuery closed 2D profile including polyline bulge arcs."""
    import cadquery as cq
    if isinstance(e,Circle):
        return cq.Workplane("XY").center(float(e.cx),float(e.cy)).circle(float(e.r))
    if not isinstance(e,Polyline) or not e.closed:return None
    prims=e.prims()
    if not prims:return None
    st=G.prim_start(prims[0]); wp=cq.Workplane("XY").moveTo(float(st[0]),float(st[1]))
    for pr in prims:
        en=G.prim_end(pr)
        if pr[0]=='L':wp=wp.lineTo(float(en[0]),float(en[1]))
        else:
            mid=G.prim_point(pr,G.prim_len(pr)*0.5)
            wp=wp.threePointArc((float(mid[0]),float(mid[1])),(float(en[0]),float(en[1])))
    return wp.close()

def _cq_wire(e, z=0.0):
    import cadquery as cq
    if isinstance(e,Circle):
        return cq.Wire.makeCircle(float(e.r),cq.Vector(float(e.cx),float(e.cy),float(z)),cq.Vector(0,0,1))
    if not isinstance(e,Polyline):return None
    edges=[]
    for pr in e.prims():
        a=G.prim_start(pr);b=G.prim_end(pr)
        if pr[0]=='L':edges.append(cq.Edge.makeLine(cq.Vector(a[0],a[1],z),cq.Vector(b[0],b[1],z)))
        else:
            m=G.prim_point(pr,G.prim_len(pr)*0.5)
            edges.append(cq.Edge.makeThreePointArc(cq.Vector(a[0],a[1],z),cq.Vector(m[0],m[1],z),cq.Vector(b[0],b[1],z)))
    return cq.Wire.assembleEdges(edges) if edges else None

def _cq_path_wire(e):
    import cadquery as cq
    if isinstance(e,Line):return cq.Wire.assembleEdges([cq.Edge.makeLine((e.x1,e.y1,0),(e.x2,e.y2,0))])
    if not isinstance(e,Polyline):return None
    edges=[]
    for pr in e.prims():
        a=G.prim_start(pr);b=G.prim_end(pr)
        if pr[0]=='L':edges.append(cq.Edge.makeLine((a[0],a[1],0),(b[0],b[1],0)))
        else:
            m=G.prim_point(pr,G.prim_len(pr)*0.5);edges.append(cq.Edge.makeThreePointArc((a[0],a[1],0),(m[0],m[1],0),(b[0],b[1],0)))
    return cq.Wire.assembleEdges(edges) if edges else None

def _basis_for_command(c):
    """Return the frozen/effective command WorkPlane axes (U,V,N)."""
    try:
        view=c._view_at(c.mouse)[0] if hasattr(c,"_view_at") else c.view
        p=c.effective_work_plane(view) if hasattr(c,"effective_work_plane") else c.work_plane(view)
        return p.u,p.v,p.n
    except Exception:
        return (1.0,0.0,0.0),(0.0,1.0,0.0),(0.0,0.0,1.0)

def _basis_vec(a,b,u,v,n):
    d=(float(b[0])-float(a[0]),float(b[1])-float(a[1]),float((b[2] if len(b)>=3 else 0.0)-(a[2] if len(a)>=3 else 0.0)))
    return (sum(d[i]*u[i] for i in range(3)),sum(d[i]*v[i] for i in range(3)),sum(d[i]*n[i] for i in range(3)))

def _basis_point(o,u,v,n,x=0.0,y=0.0,z=0.0):
    oz=float(o[2]) if len(o)>=3 else 0.0
    return (float(o[0])+u[0]*x+v[0]*y+n[0]*z,
            float(o[1])+u[1]*x+v[1]*y+n[1]*z,
            oz+u[2]*x+v[2]*y+n[2]*z)

def _ring_plane(cen,u,v,r,count=32,normal_offset=0.0,n=(0,0,1)):
    out=[]
    for i in range(count):
        a=2*math.pi*i/count
        out.append(_basis_point(cen,u,v,n,r*math.cos(a),r*math.sin(a),normal_offset))
    return out

def _box_geom(a, b, h):
    x0, x1 = sorted((a[0], b[0])); y0, y1 = sorted((a[1], b[1]))
    bz=float(a[2]) if len(a)>=3 else 0.0
    z0, z1 = (bz, bz+float(h)) if h >= 0 else (bz+float(h), bz)
    v = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
         (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    e = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    f = [(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]
    return v,e,f


def BOX(c):
    a = yield pt("指定方塊的第一個角點")
    if not is_pt(a): return
    b = yield pt("指定另一個角點", base=a)
    if not is_pt(b): return
    u,v,n=_basis_for_command(c); du,dv,_dw=_basis_vec(a,b,u,v,n)
    h = yield num("指定高度（沿工作平面法向）", default=max(abs(du),abs(dv),10.0))
    if not isinstance(h,(int,float)) or abs(h)<1e-12:return
    x0,x1=sorted((0.0,du));y0,y1=sorted((0.0,dv));hh=float(h)
    loc=[(x0,y0,0),(x1,y0,0),(x1,y1,0),(x0,y1,0),(x0,y0,hh),(x1,y0,hh),(x1,y1,hh),(x0,y1,hh)]
    vv=[_basis_point(a,u,v,n,*q) for q in loc]
    ed=[(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    ff=[(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]
    fb=_solid(c,vv,ed,ff,"BOX")
    try:
        sh=_cq_polyhedron(vv,ff);fb=_prefer_exact(c,fb,sh,"BOX") if sh is not None else fb
    except Exception:pass
    c.add(fb);c.changed()


def _ring(cx, cy, z, r, n=32):
    return [(cx + r*math.cos(2*math.pi*i/n), cy + r*math.sin(2*math.pi*i/n), z) for i in range(n)]


def CYLINDER(c):
    cen=yield pt("指定圓柱底面的中心點")
    if not is_pt(cen):return
    r=yield pt("指定底面半徑",base=cen,number=True,default=10.0)
    if is_pt(r):r=_point_distance(cen,r)
    if not isinstance(r,(int,float)) or r<=0:return
    h=yield num("指定高度（沿工作平面法向）",default=float(r)*2.0)
    if not isinstance(h,(int,float)) or abs(h)<1e-12:return
    u,v,n=_basis_for_command(c);count=32;rr=float(r);hh=float(h)
    vv=_ring_plane(cen,u,v,rr,count,0.0,n)+_ring_plane(cen,u,v,rr,count,hh,n)
    ed=[]
    for i in range(count):
        j=(i+1)%count;ed += [(i,j),(count+i,count+j)]
        if i%4==0:ed.append((i,count+i))
    ff=[tuple(reversed(range(count))),tuple(range(count,2*count))]+[(i,(i+1)%count,count+(i+1)%count,count+i) for i in range(count)]
    fb=_solid(c,vv,ed,ff,"CYLINDER")
    try:
        import cadquery as cq
        direction=tuple(x*(1.0 if hh>=0 else -1.0) for x in n)
        sh=cq.Solid.makeCylinder(rr,abs(hh),cq.Vector(*map(float,cen[:3])),cq.Vector(*direction))
        fb=_prefer_exact(c,fb,sh,"CYLINDER")
    except Exception:pass
    c.add(fb);c.changed()


def CONE(c):
    cen=yield pt("指定圓錐底面的中心點")
    if not is_pt(cen):return
    r=yield pt("指定底面半徑",base=cen,number=True,default=10.0)
    if is_pt(r):r=_point_distance(cen,r)
    if not isinstance(r,(int,float)) or r<=0:return
    h=yield num("指定高度（沿工作平面法向）",default=float(r)*2.0)
    if not isinstance(h,(int,float)) or abs(h)<1e-12:return
    u,v,n=_basis_for_command(c);count=32;rr=float(r);hh=float(h)
    vv=_ring_plane(cen,u,v,rr,count,0.0,n)+[_basis_point(cen,u,v,n,0,0,hh)];apex=count
    ed=[(i,(i+1)%count) for i in range(count)]+[(i,apex) for i in range(0,count,4)]
    ff=[tuple(reversed(range(count)))]+[(i,(i+1)%count,apex) for i in range(count)]
    fb=_solid(c,vv,ed,ff,"CONE")
    try:
        import cadquery as cq
        direction=tuple(x*(1.0 if hh>=0 else -1.0) for x in n)
        sh=cq.Solid.makeCone(rr,0.0,abs(hh),cq.Vector(*map(float,cen[:3])),cq.Vector(*direction))
        fb=_prefer_exact(c,fb,sh,"CONE")
    except Exception:pass
    c.add(fb);c.changed()


def SPHERE(c):
    cen=yield pt("指定球體中心點")
    if not is_pt(cen):return
    r=yield pt("指定半徑",base=cen,number=True,default=10.0)
    if is_pt(r):r=_point_distance(cen,r)
    if not isinstance(r,(int,float)) or r<=0:return
    rr=float(r);lon=32;lat=16;u,v,n=_basis_for_command(c);vv=[];ed=[];ff=[]
    vv.append(_basis_point(cen,u,v,n,0,0,rr))
    for j in range(1,lat):
        ph=math.pi*j/lat; z=rr*math.cos(ph);rad=rr*math.sin(ph)
        for i in range(lon):
            a=2*math.pi*i/lon;vv.append(_basis_point(cen,u,v,n,rad*math.cos(a),rad*math.sin(a),z))
    south=len(vv);vv.append(_basis_point(cen,u,v,n,0,0,-rr))
    def ring(j,i):return 1+(j-1)*lon+(i%lon)
    for i in range(lon):
        a=ring(1,i);b=ring(1,i+1);ff.append((0,b,a));ed += [(0,a),(a,b)]
    for j in range(1,lat-1):
        for i in range(lon):
            a=ring(j,i);b=ring(j,i+1);c0=ring(j+1,i+1);d=ring(j+1,i);ff.append((a,b,c0,d))
            if j in (1,lat//2,lat-2) or i%8==0:ed += [(a,b),(a,d)]
    for i in range(lon):
        a=ring(lat-1,i);b=ring(lat-1,i+1);ff.append((a,b,south));ed += [(a,b),(a,south)]
    seen=set();edges=[]
    for a,b in ed:
        k=tuple(sorted((a,b)))
        if k not in seen:seen.add(k);edges.append((a,b))
    fb=_solid(c,vv,edges,ff,"SPHERE")
    try:
        import cadquery as cq
        sh=cq.Solid.makeSphere(rr,cq.Vector(*map(float,cen[:3])),cq.Vector(*n),-90.0,90.0,360.0)
        fb=_prefer_exact(c,fb,sh,"SPHERE")
    except Exception:pass
    c.add(fb);c.changed()


def EXTRUDE(c):
    ents = yield sel("選取要擠出的封閉 2D 物件")
    if not ents:return
    h = yield num("指定擠出高度", default=10.0)
    if not isinstance(h,(int,float)) or abs(h)<1e-12:return
    out=[]
    for src in ents:
        if not (isinstance(src,Circle) or (isinstance(src,Polyline) and src.closed)):
            continue
        try:
            prof=_cq_profile(src)
            sh=prof.extrude(float(h)).val() if prof is not None else None
            if sh is not None:
                ss=_cq_to_solid(c,sh,"EXTRUDE",deflection=0.35)
                if ss:out.append(ss);continue
        except Exception:
            pass
        # dependency-free fallback uses an arc-tessellated profile, including concave loops.
        pts=_closed_profile_points(src,64)
        if not pts:continue
        n=len(pts);v=[(x,y,0.0) for x,y in pts]+[(x,y,float(h)) for x,y in pts];ed=[]
        for i in range(n):
            j=(i+1)%n;ed += [(i,j),(n+i,n+j),(i,n+i)]
        # side faces are exact; caps are triangulated by CadQuery whenever available.
        faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]+[(i,(i+1)%n,n+(i+1)%n,n+i) for i in range(n)]
        out.append(_solid(c,v,ed,faces,"EXTRUDE"))
    if out:
        c.add_many(out);c.changed();c.keep_selection(out)
    else:c.msg("EXTRUDE：請選取圓或封閉聚合線。")



def PRESSPULL(c):
    """Press/pull a picked closed 2D region.  Unlike the old EXTRUDE alias,
    this uses boundary detection at the picked point and preserves islands as holes."""
    q=yield pt("在封閉區域內指定一點")
    if not is_pt(q):return
    loops=E.find_boundary(c.doc,(q[0],q[1]),c.view_rect())
    if not loops:
        c.msg("PRESSPULL：找不到封閉邊界。") ; return
    h=yield num("指定按拉高度",default=10.0)
    if not isinstance(h,(int,float)) or abs(h)<1e-12:return
    try:
        import cadquery as cq
        def wire(lp):return cq.Wire.makePolygon([cq.Vector(float(x),float(y),0.0) for x,y in lp],close=True)
        outer=wire(loops[0]);inners=[wire(lp) for lp in loops[1:]]
        sh=cq.Solid.extrudeLinear(outer,inners,cq.Vector(0,0,float(h)))
        ss=_cq_to_solid(c,sh,"PRESSPULL",deflection=0.45)
        if ss:c.add(ss);c.changed();c.keep_selection([ss]);return
    except Exception as ex:
        c.msg("PRESSPULL 精確核心失敗：%s"%ex)
    # Dependency-free fallback keeps the outer region; exact holes require OCC.
    lp=loops[0];n=len(lp);v=[(x,y,0.0) for x,y in lp]+[(x,y,float(h)) for x,y in lp];ed=[]
    for i in range(n):j=(i+1)%n;ed += [(i,j),(n+i,n+j),(i,n+i)]
    faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]+[(i,(i+1)%n,n+(i+1)%n,n+i) for i in range(n)]
    ss=_solid(c,v,ed,faces,"PRESSPULL");c.add(ss);c.changed();c.keep_selection([ss])


# ================================================================ 3D 建模（v0.6.2）
def WEDGE(c):
    a=yield pt("指定楔體第一角點")
    if not is_pt(a):return
    b=yield pt("指定另一角點",base=a)
    if not is_pt(b):return
    u,v,n=_basis_for_command(c);du,dv,_=_basis_vec(a,b,u,v,n)
    h=yield num("指定高度（沿工作平面法向）",default=max(abs(du),abs(dv),10.0))
    if not isinstance(h,(int,float)) or abs(h)<1e-12:return
    x0,x1=sorted((0.0,du));y0,y1=sorted((0.0,dv));hh=float(h)
    loc=[(x0,y0,0),(x1,y0,0),(x1,y1,0),(x0,y1,0),(x0,y0,hh),(x0,y1,hh)]
    vv=[_basis_point(a,u,v,n,*q) for q in loc]
    ed=[(0,1),(1,2),(2,3),(3,0),(0,4),(3,5),(4,5),(1,4),(2,5)]
    ff=[(0,3,2,1),(0,4,5,3),(0,1,4),(3,5,2),(1,2,5,4)]
    fb=_solid(c,vv,ed,ff,"WEDGE")
    try:
        sh=_cq_polyhedron(vv,ff);fb=_prefer_exact(c,fb,sh,"WEDGE") if sh is not None else fb
    except Exception:pass
    c.add(fb);c.changed()


def PYRAMID(c):
    cen=yield pt("指定金字塔底面中心點")
    if not is_pt(cen):return
    r=yield num("指定底面半徑",default=10.0)
    if not isinstance(r,(int,float)) or r<=0:return
    sides=yield num("指定邊數 <4>",default=4)
    if not isinstance(sides,(int,float)):return
    count=max(3,min(64,int(sides)))
    h=yield num("指定高度（沿工作平面法向）",default=float(r)*1.5)
    if not isinstance(h,(int,float)) or abs(h)<1e-12:return
    u,v,n=_basis_for_command(c);rr=float(r);hh=float(h)
    vv=[_basis_point(cen,u,v,n,rr*math.cos(2*math.pi*i/count),rr*math.sin(2*math.pi*i/count),0) for i in range(count)]
    apex=len(vv);vv.append(_basis_point(cen,u,v,n,0,0,hh))
    ed=[(i,(i+1)%count) for i in range(count)]+[(i,apex) for i in range(count)]
    ff=[tuple(reversed(range(count)))]+[(i,(i+1)%count,apex) for i in range(count)]
    fb=_solid(c,vv,ed,ff,"PYRAMID")
    try:
        sh=_cq_polyhedron(vv,ff);fb=_prefer_exact(c,fb,sh,"PYRAMID") if sh is not None else fb
    except Exception:pass
    c.add(fb);c.changed()


def TORUS(c):
    cen=yield pt("指定圓環中心點")
    if not is_pt(cen):return
    R=yield num("指定主半徑",default=15.0)
    if not isinstance(R,(int,float)) or R<=0:return
    r=yield num("指定管半徑",default=max(1.0,float(R)/4))
    if not isinstance(r,(int,float)) or r<=0 or r>=R:return
    u,v,n=_basis_for_command(c);nu,nv=32,16;vv=[];ff=[];ed=[];R=float(R);r=float(r)
    for i in range(nu):
        a=2*math.pi*i/nu;radial=tuple(math.cos(a)*u[k]+math.sin(a)*v[k] for k in range(3))
        for j in range(nv):
            w=2*math.pi*j/nv;dist=R+r*math.cos(w)
            vv.append((float(cen[0])+radial[0]*dist+n[0]*r*math.sin(w),float(cen[1])+radial[1]*dist+n[1]*r*math.sin(w),float(cen[2])+radial[2]*dist+n[2]*r*math.sin(w)))
    idx=lambda i,j:(i%nu)*nv+(j%nv)
    for i in range(nu):
        for j in range(nv):
            a,b,d,e0=idx(i,j),idx(i+1,j),idx(i+1,j+1),idx(i,j+1);ff.append((a,b,d,e0))
            if j in (0,nv//4,nv//2,3*nv//4) or i%8==0:ed += [(a,b),(a,e0)]
    seen=set();edges=[]
    for a,b in ed:
        k=tuple(sorted((a,b)))
        if k not in seen:seen.add(k);edges.append((a,b))
    fb=_solid(c,vv,edges,ff,"TORUS")
    try:
        import cadquery as cq
        sh=cq.Solid.makeTorus(R,r,cq.Vector(*map(float,cen[:3])),cq.Vector(*n));fb=_prefer_exact(c,fb,sh,"TORUS")
    except Exception:pass
    c.add(fb);c.changed()


def _p3(q):
    if not is_pt(q):return None
    return (float(q[0]),float(q[1]),float(q[2]) if len(q)>=3 else 0.0)


def _translate_solid3d(s0, dx, dy, dz):
    """Translate a Solid3D while preserving exact BREP whenever possible."""
    ns=s0.clone(vertices=[(x+dx,y+dy,z+dz) for x,y,z in s0.vertices],brep_b64="")
    try:
        from .io_utils import _cq_shape_from_solid,_shape_to_brep_b64
        sh=_cq_shape_from_solid(s0,1.0).translate((float(dx),float(dy),float(dz)))
        ns.brep_b64=_shape_to_brep_b64(sh)
    except Exception:
        pass
    return ns


def _face_frame_from_canvas(c):
    """Return (origin,u,v,n) for the currently acquired visible Solid3D face.

    The normal is oriented outwards relative to the solid bounding-box centre.  The
    face centre is used as the local UV origin, making numeric U/V/N placement stable
    even when the solid or the viewing direction is rotated.
    """
    if hasattr(c,"face_frame3d"):
        try:
            q=c.face_frame3d()
            if q is not None:return q
        except Exception:pass
    hit=getattr(c,"last_subface",None)
    if not hit:return None
    solid,face=hit
    if not isinstance(solid,Solid3D):return None
    ids=[int(i) for i in face if 0<=int(i)<len(solid.vertices)]
    if len(ids)<3:return None
    pts=[solid.vertices[i] for i in ids]
    cen=(sum(q[0] for q in pts)/len(pts),sum(q[1] for q in pts)/len(pts),sum(q[2] for q in pts)/len(pts))
    # Prefer the longest polygon edge as local U; it is much less noisy on tessellated faces.
    best=None
    for a,b in zip(pts,pts[1:]+pts[:1]):
        d=(b[0]-a[0],b[1]-a[1],b[2]-a[2]);L=sum(x*x for x in d)
        if best is None or L>best[0]:best=(L,d)
    if best is None or best[0]<1e-24:return None
    L=math.sqrt(best[0]);u=tuple(x/L for x in best[1])
    a,b,d=pts[0],pts[1],pts[2]
    ab=(b[0]-a[0],b[1]-a[1],b[2]-a[2]);ac=(d[0]-a[0],d[1]-a[1],d[2]-a[2])
    n=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
    nl=math.sqrt(sum(x*x for x in n))
    if nl<1e-12:return None
    n=tuple(x/nl for x in n)
    bb=solid.bbox3d()
    if bb:
        sc=((bb[0]+bb[3])*0.5,(bb[1]+bb[4])*0.5,(bb[2]+bb[5])*0.5)
        outward=(cen[0]-sc[0],cen[1]-sc[1],cen[2]-sc[2])
        if sum(n[i]*outward[i] for i in range(3))<0:n=tuple(-x for x in n)
    # Re-orthogonalise U against N, then derive V.
    du=sum(u[i]*n[i] for i in range(3));u=tuple(u[i]-du*n[i] for i in range(3));ul=math.sqrt(sum(x*x for x in u))
    if ul<1e-12:return None
    u=tuple(x/ul for x in u)
    v=(n[1]*u[2]-n[2]*u[1],n[2]*u[0]-n[0]*u[2],n[0]*u[1]-n[1]*u[0])
    vl=math.sqrt(sum(x*x for x in v));v=tuple(x/vl for x in v)
    return cen,u,v,n


def PLACE3D(c):
    """Practical placement: where to attach -> which direction -> how many mm."""
    ents=yield sel("選取要定位的 3D 實體")
    solids=[e for e in ents if isinstance(e,Solid3D)]
    if not solids:return
    src=yield pt("指定來源基準點（例如圓柱底面中心）")
    if not is_pt(src):return
    src=_p3(src)
    target=yield pt("你想把它貼哪裡？請點選目標面上的位置",face_pick=True)
    if not is_pt(target):return
    target=_p3(target);frame=_face_frame_from_canvas(c)
    if frame is None:
        c.msg("PLACE3D：沒有取得有效目標面。可在任何視覺型式直接點 3D 面。") ; return
    origin,u,v,n=frame
    mode=yield kwd("貼合後要往哪個方向？",(("I","向實體內"),("O","向外"),("X","世界 X"),("Y","世界 Y"),("Z","世界 Z"),("U","面內 U"),("V","面內 V"),("A","進階 U/V/N"),("P","進階：以點為原點"),("C","進階：以面中心為原點")),default=Kw("I"))
    if mode is None:return
    if mode in ("A","P","C"):
        du=yield num("面內 U 偏移",default=0.0); dv=yield num("面內 V 偏移",default=0.0); dn=yield num("法向 N 偏移（負值向內）",default=0.0)
        if not all(isinstance(x,(int,float)) for x in (du,dv,dn)):return
        anchor=origin if mode=="C" else target
        dest=(anchor[0]+u[0]*du+v[0]*dv+n[0]*dn,anchor[1]+u[1]*du+v[1]*dv+n[1]*dn,anchor[2]+u[2]*du+v[2]*dv+n[2]*dn)
        desc="U=%s V=%s N=%s"%(fmt(du,4),fmt(dv,4),fmt(dn,4))
    else:
        mm=yield num("要移動幾 mm？",default=0.0)
        if not isinstance(mm,(int,float)):return
        dirs={"I":tuple(-x for x in n),"O":n,"X":(1.0,0.0,0.0),"Y":(0.0,1.0,0.0),"Z":(0.0,0.0,1.0),"U":u,"V":v}
        d=dirs.get(str(mode),tuple(-x for x in n));dest=tuple(target[i]+d[i]*float(mm) for i in range(3));desc="%s %s mm"%(mode,fmt(mm,4))
    dx,dy,dz=(dest[i]-src[i] for i in range(3));out=[]
    for s0 in solids:
        ns=_translate_solid3d(s0,dx,dy,dz);c.replace(s0,ns);out.append(ns)
    c.msg("PLACE3D：已貼合；%s；ΔX=%s ΔY=%s ΔZ=%s"%(desc,fmt(dx,4),fmt(dy,4),fmt(dz,4)))
    c.changed();c.keep_selection(out)


def MOVE3D(c):
    ents=yield sel("選取要 3D 移動的物件")
    solids=[e for e in ents if isinstance(e,Solid3D)]
    if not solids:return
    a=yield pt("指定基準點 (可輸入 X,Y,Z)")
    if not is_pt(a):return
    b=yield pt("指定第二點 (可輸入 X,Y,Z)",base=a)
    if not is_pt(b):return
    a3,b3=_p3(a),_p3(b);dx,dy,dz=(b3[i]-a3[i] for i in range(3))
    out=[]
    for s0 in solids:
        ns=_translate_solid3d(s0,dx,dy,dz)
        c.replace(s0,ns);out.append(ns)
    c.changed();c.keep_selection(out)

def ROTATE3D(c):
    ents=yield sel("選取要 3D 旋轉的物件")
    solids=[e for e in ents if isinstance(e,Solid3D)]
    if not solids:return
    base=yield pt("指定基準點 (可輸入 X,Y,Z)")
    if not is_pt(base):return
    b3=_p3(base)
    axis=yield kwd("指定旋轉軸", (("X","X 軸"),("Y","Y 軸"),("Z","Z 軸")), default="Z")
    if axis is None:return
    ang=yield num("指定旋轉角度",default=90.0)
    if not isinstance(ang,(int,float)):return
    a=math.radians(float(ang));ca,sa=math.cos(a),math.sin(a)
    def rot(v):
        x,y,z=v[0]-b3[0],v[1]-b3[1],v[2]-b3[2]
        if axis=="X":q=(x,y*ca-z*sa,y*sa+z*ca)
        elif axis=="Y":q=(x*ca+z*sa,y,-x*sa+z*ca)
        else:q=(x*ca-y*sa,x*sa+y*ca,z)
        return (q[0]+b3[0],q[1]+b3[1],q[2]+b3[2])
    out=[]
    for s0 in solids:
        ns=s0.clone(vertices=[rot(v) for v in s0.vertices],brep_b64="")
        try:
            from .io_utils import _cq_shape_from_solid,_shape_to_brep_b64
            sh=_cq_shape_from_solid(s0,1.0)
            av={"X":(1,0,0),"Y":(0,1,0),"Z":(0,0,1)}[axis]
            sh=sh.rotate(b3,(b3[0]+av[0],b3[1]+av[1],b3[2]+av[2]),float(ang))
            ns.brep_b64=_shape_to_brep_b64(sh)
        except Exception:pass
        c.replace(s0,ns);out.append(ns)
    c.changed();c.keep_selection(out)

def SCALE3D(c):
    ents=yield sel("選取要 3D 比例縮放的物件")
    solids=[e for e in ents if isinstance(e,Solid3D)]
    if not solids:return
    base=yield pt("指定基準點 (可輸入 X,Y,Z)")
    if not is_pt(base):return
    b3=_p3(base)
    k=yield num("指定比例係數",default=1.0)
    if not isinstance(k,(int,float)) or k<=0:return
    out=[]
    for s0 in solids:
        ns=s0.clone(vertices=[(b3[0]+(x-b3[0])*k,b3[1]+(y-b3[1])*k,b3[2]+(z-b3[2])*k) for x,y,z in s0.vertices],brep_b64="")
        try:
            from .io_utils import _cq_shape_from_solid,_shape_to_brep_b64
            sh=_cq_shape_from_solid(s0,1.0).translate((-b3[0],-b3[1],-b3[2])).scale(float(k)).translate(b3)
            ns.brep_b64=_shape_to_brep_b64(sh)
        except Exception:pass
        c.replace(s0,ns);out.append(ns)
    c.changed();c.keep_selection(out)


def _cq_to_solid(c, shape, name="BOOLEAN", deflection=0.65):
    """Convert exact OCC shape to a lightweight display mesh while retaining exact BREP."""
    try:
        bb=shape.BoundingBox(); diag=max((bb.xlen*bb.xlen+bb.ylen*bb.ylen+bb.zlen*bb.zlen)**0.5,1.0)
        tol=max(float(deflection),diag/260.0)
        verts,tris=shape.tessellate(tol)
        # Display mesh is only a cache.  Keep exact BREP authoritative and coarsen
        # pathological fillets/booleans until mouse interaction remains responsive.
        tries=0
        while len(tris)>7000 and tries<5:
            tol*=1.7; verts,tris=shape.tessellate(tol); tries+=1
    except Exception as ex:
        c.msg("3D 核心轉換失敗：%s"%ex);return None
    vv=[(float(v.x),float(v.y),float(v.z)) for v in verts]
    ff=[tuple(map(int,t)) for t in tris]
    # Keep only feature/crease edges rather than every tessellation diagonal.  The
    # previous version exposed thousands of triangle edges after FILLETEDGE.
    normals=[]
    for f in ff:
        a,b,d=(vv[i] for i in f[:3]); ux,uy,uz=b[0]-a[0],b[1]-a[1],b[2]-a[2]; vx,vy,vz=d[0]-a[0],d[1]-a[1],d[2]-a[2]
        nx,ny,nz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx;L=max((nx*nx+ny*ny+nz*nz)**0.5,1e-12)
        normals.append((nx/L,ny/L,nz/L))
    adj={}
    for fi,f in enumerate(ff):
        for a,b in ((f[0],f[1]),(f[1],f[2]),(f[2],f[0])):adj.setdefault(tuple(sorted((a,b))),[]).append(fi)
    ed=[]
    cos_limit=math.cos(math.radians(24.0))
    for edge,fs in adj.items():
        keep=len(fs)==1
        if len(fs)>=2:
            n1,n2=normals[fs[0]],normals[fs[1]]; dot=sum(n1[i]*n2[i] for i in range(3))
            keep=dot<cos_limit
        if keep:ed.append(edge)
    if len(ed)<12 and adj:
        keys=list(adj); stride=max(1,len(keys)//160); ed=list(dict.fromkeys(ed+keys[::stride]))[:300]
    out=_solid(c,vv,ed,ff,name)
    try:
        from .io_utils import _shape_to_brep_b64
        out.brep_b64=_shape_to_brep_b64(shape)
    except Exception:pass
    return out


def _shape_volume(sh):
    try:return float(sh.Volume())
    except Exception:return 0.0


def _bool3d(c, op):
    try:
        from .io_utils import _cq_shape_from_solid
    except Exception as ex:
        c.msg(op+" 需要 CadQuery/OpenCascade：%s"%ex);return

    if op=="SUBTRACT":
        bases=yield sel("選取被減實體（Base），Enter 完成")
        base_solids=[e for e in bases if isinstance(e,Solid3D)]
        if not base_solids:
            c.msg("SUBTRACT：請至少選取一個被減 3D 實體。") ; return
        tools=yield sel("選取要減去的實體（Tool），Enter 完成")
        base_ids={id(e) for e in base_solids}
        tool_solids=[e for e in tools if isinstance(e,Solid3D) and id(e) not in base_ids]
        if not tool_solids:
            c.msg("SUBTRACT：請至少選取一個不同的 Tool 實體。") ; return
        try:
            tool_shapes=[_cq_shape_from_solid(s,1.0) for s in tool_solids]
            out=[];any_overlap=False
            for base in base_solids:
                result=_cq_shape_from_solid(base,1.0);base_overlap=False
                for tool,sh in zip(tool_solids,tool_shapes):
                    inter=result.intersect(sh);iv=_shape_volume(inter)
                    # Scale-aware volume epsilon: reject contact-only and numerical dust.
                    bb=result.BoundingBox();scale=max(bb.xlen,bb.ylen,bb.zlen,1.0);eps=max(scale**3*1e-10,1e-9)
                    if iv<=eps:
                        continue
                    base_overlap=True;any_overlap=True;result=result.cut(sh)
                if base_overlap:
                    ns=_cq_to_solid(c,result,"SUBTRACT")
                    if ns is not None:
                        c.replace(base,ns);out.append(ns)
                else:
                    out.append(base)
            if not any_overlap:
                c.msg("SUBTRACT：Base 與 Tool 沒有有效體積交集（可能只是接觸），未執行差集。")
                return
            # Consume tools only after at least one successful volumetric cut.
            c.remove(tool_solids);c.changed();c.keep_selection(out)
            c.msg("SUBTRACT：已依 Base → Tool 順序完成差集。")
        except Exception as ex:
            c.msg("SUBTRACT 幾何布林失敗：%s"%ex)
        return

    ents=yield sel("選取 2 個以上 3D 實體")
    solids=[e for e in ents if isinstance(e,Solid3D)]
    if len(solids)<2:
        c.msg(op+"：至少需要兩個 3D 實體。") ; return
    try:
        shapes=[_cq_shape_from_solid(s,1.0) for s in solids]
        result=shapes[0]
        for sh in shapes[1:]:
            result=result.fuse(sh) if op=="UNION" else result.intersect(sh)
        if op=="INTERSECT" and _shape_volume(result)<=1e-9:
            c.msg("INTERSECT：所選實體沒有有效體積交集。")
            return
        ns=_cq_to_solid(c,result,op)
        if ns is None:return
        c.remove(solids); c.add(ns); c.changed(); c.keep_selection([ns])
    except Exception as ex:
        c.msg(op+" 需要 CadQuery/OpenCascade，或幾何布林失敗：%s" % ex)


def UNION(c):
    yield from _bool3d(c,"UNION")
def SUBTRACT(c):
    yield from _bool3d(c,"SUBTRACT")
def INTERSECT(c):
    yield from _bool3d(c,"INTERSECT")



# ================================================================ 3D 建模（v0.6.3）
def _closed_profile_points(e, samples=48):
    """Return a planar XY profile, tessellating polyline bulge arcs instead of dropping them."""
    if isinstance(e, Circle):
        return [(e.cx + e.r*math.cos(2*math.pi*i/samples), e.cy + e.r*math.sin(2*math.pi*i/samples)) for i in range(samples)]
    if isinstance(e, Polyline) and e.closed and len(e.pts) >= 3:
        out=[]
        for pr in e.prims():
            if pr[0]=='L':
                q=G.prim_start(pr)
                if not out or G.dist(out[-1],q)>1e-9:out.append((float(q[0]),float(q[1])))
            else:
                L=max(G.prim_len(pr),1e-12)
                # about 7.5 degrees per chord, capped for predictable performance
                n=max(2,min(96,int(math.ceil(float(pr[5])/7.5))))
                for i in range(n):
                    q=G.prim_point(pr,L*i/n)
                    if not out or G.dist(out[-1],q)>1e-9:out.append((float(q[0]),float(q[1])))
        return out if len(out)>=3 else None
    return None


def _resample_loop(pts, n):
    if len(pts)==n: return list(pts)
    seg=[]; total=0.0
    for i in range(len(pts)):
        a,b=pts[i],pts[(i+1)%len(pts)]; L=G.dist(a,b); seg.append(L); total+=L
    if total < 1e-12:return [pts[0]]*n
    out=[]
    for k in range(n):
        d=total*k/n; acc=0.0
        for i,L in enumerate(seg):
            if d <= acc+L or i==len(seg)-1:
                t=0.0 if L<1e-12 else (d-acc)/L; a,b=pts[i],pts[(i+1)%len(pts)]
                out.append((a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t)); break
            acc+=L
    return out


def REVOLVE(c):
    ents=yield sel("選取要旋轉成實體的封閉 2D 輪廓")
    profiles=[e for e in ents if _closed_profile_points(e)]
    if not profiles:c.msg("REVOLVE：請選取圓或封閉聚合線。");return
    axis=yield kwd("指定旋轉軸", (("X","X 軸"),("Y","Y 軸")), default="Y")
    if axis is None:return
    origin=yield num("指定旋轉軸座標",default=0.0);ang=yield num("指定旋轉角度 <360>",default=360.0)
    if not isinstance(origin,(int,float)) or not isinstance(ang,(int,float)) or abs(ang)<1e-9:return
    out=[]
    for src in profiles:
        prof=_closed_profile_points(src)
        vals=[p[1] if axis=='X' else p[0] for p in prof]
        if vals and min(vals)<float(origin)-1e-9 and max(vals)>float(origin)+1e-9:
            c.msg("REVOLVE：輪廓跨越旋轉軸，會產生自交/無效實體；已拒絕，請先修剪輪廓到軸的一側。")
            continue
        try:
            import cadquery as cq
            w=_cq_wire(src,0.0)
            a0=(0,float(origin),0) if axis=='X' else (float(origin),0,0)
            a1=(1,float(origin),0) if axis=='X' else (float(origin),1,0)
            sh=cq.Solid.revolve(w,[],float(ang),a0,a1)
            ss=_cq_to_solid(c,sh,"REVOLVE",0.45)
            if ss:out.append(ss);continue
        except Exception as ex:
            c.msg("REVOLVE 精確核心失敗，未建立可能錯誤的替代網格：%s"%ex)
            continue
        n=len(prof);steps=max(8,min(128,int(abs(float(ang))/7.5)+1));full=abs(abs(float(ang))-360)<1e-7;v=[];rings=steps if full else steps+1
        for j in range(rings):
            aa=math.radians(float(ang)*(j/steps));ca,sa=math.cos(aa),math.sin(aa)
            for x,y in prof:
                if axis=='Y':dx=x-float(origin);v.append((float(origin)+dx*ca,y,dx*sa))
                else:dy=y-float(origin);v.append((x,float(origin)+dy*ca,dy*sa))
        faces=[];ed=[];jmax=rings if full else rings-1
        for j in range(jmax):
            j2=(j+1)%rings
            for i in range(n):i2=(i+1)%n;a=j*n+i;b=j*n+i2;d=j2*n+i2;e0=j2*n+i;faces.append((a,b,d,e0));ed += [(a,b),(a,e0)]
        if not full:faces += [tuple(reversed(range(n))),tuple((rings-1)*n+i for i in range(n))]
        out.append(_solid(c,v,ed,faces,"REVOLVE"))
    if out:c.add_many(out);c.changed();c.keep_selection(out)


def SWEEP(c):
    ents=yield sel("選取 1 個圓形截面與 1 條路徑（線或聚合線）")
    circle=next((e for e in ents if isinstance(e,Circle)),None);path=next((e for e in ents if isinstance(e,Polyline) and len(e.pts)>=2),None);line=next((e for e in ents if isinstance(e,Line)),None)
    path_ent=line or path
    if circle is None or path_ent is None:c.msg("SWEEP：目前支援『圓 + 線/聚合線路徑』。");return
    try:
        import cadquery as cq
        pts=[(line.x1,line.y1),(line.x2,line.y2)] if line is not None else [(float(q[0]),float(q[1])) for q in path.pts]
        p0,p1=pts[0],pts[1];tx,ty=p1[0]-p0[0],p1[1]-p0[1];L=math.hypot(tx,ty) or 1.0
        profile=cq.Wire.makeCircle(float(circle.r),cq.Vector(p0[0],p0[1],0),cq.Vector(tx/L,ty/L,0))
        pathw=_cq_path_wire(path_ent);sh=cq.Solid.sweep(profile,[],pathw,True,True)
        ss=_cq_to_solid(c,sh,"SWEEP",0.45)
        if ss:c.add(ss);c.changed();c.keep_selection([ss]);return
    except Exception as ex:
        c.msg("SWEEP 精確核心失敗，改用顯示網格：%s"%ex)
    if line is not None:
        pts=[(line.x1,line.y1),(line.x2,line.y2)]
    else:
        # Fallback follows the actual polyline geometry, including bulge arcs, instead
        # of connecting only its stored vertices with straight chords.
        pts=G.flatten_prims(path.prims(),3.0)
        if path.closed and len(pts)>1 and G.dist(pts[0],pts[-1])<1e-9:
            pts=pts[:-1]
    if len(pts)<2:return
    n=24;v=[]
    for k,p0 in enumerate(pts):
        q=pts[1] if k==0 else pts[k-1];tx,ty=(q[0]-p0[0],q[1]-p0[1]) if k==0 else (p0[0]-q[0],p0[1]-q[1]);L=math.hypot(tx,ty) or 1;nx,ny=-ty/L,tx/L
        for i in range(n):aa=2*math.pi*i/n;rr=circle.r;v.append((p0[0]+nx*rr*math.cos(aa),p0[1]+ny*rr*math.cos(aa),rr*math.sin(aa)))
    faces=[];ed=[];m=len(pts)
    for k in range(m-1):
        for i in range(n):i2=(i+1)%n;a=k*n+i;b=k*n+i2;d=(k+1)*n+i2;e0=(k+1)*n+i;faces.append((a,b,d,e0));ed += [(a,b),(a,e0)]
    faces += [tuple(reversed(range(n))),tuple((m-1)*n+i for i in range(n))];ss=_solid(c,v,ed,faces,"SWEEP");c.add(ss);c.changed();c.keep_selection([ss])


def LOFT(c):
    ents=yield sel("選取至少 2 個封閉截面（圓或封閉聚合線）")
    srcs=[e for e in ents if _closed_profile_points(e)]
    try:srcs.sort(key=lambda e:c.doc.entities.index(e))
    except Exception:pass
    if len(srcs)<2:c.msg("LOFT：至少需要兩個封閉截面。");return
    dz=yield num("指定截面之間的 Z 高度",default=10.0)
    if not isinstance(dz,(int,float)) or abs(dz)<1e-12:return
    try:
        import cadquery as cq
        wires=[_cq_wire(e,float(dz)*j) for j,e in enumerate(srcs)];sh=cq.Solid.makeLoft(wires,False);ss=_cq_to_solid(c,sh,"LOFT",0.45)
        if ss:c.add(ss);c.changed();c.keep_selection([ss]);return
    except Exception as ex:c.msg("LOFT 精確核心失敗，改用顯示網格：%s"%ex)
    profs=[_closed_profile_points(e) for e in srcs];n=max(16,min(96,max(len(p) for p in profs)));profs=[_resample_loop(p,n) for p in profs];v=[]
    for j,pf in enumerate(profs):v += [(x,y,float(dz)*j) for x,y in pf]
    faces=[];ed=[];m=len(profs)
    for j in range(m-1):
        for i in range(n):i2=(i+1)%n;a=j*n+i;b=j*n+i2;d=(j+1)*n+i2;e0=(j+1)*n+i;faces.append((a,b,d,e0));ed += [(a,b),(a,e0)]
    faces += [tuple(reversed(range(n))),tuple((m-1)*n+i for i in range(n))];ss=_solid(c,v,ed,faces,"LOFT");c.add(ss);c.changed();c.keep_selection([ss])


def _cq_modify_edges(c, opname):
    all_edges=False
    r=yield ent("選取 3D 實體上的邊或",kw=(("A","全部邊"),),types=(Solid3D,))
    if r=="A":
        all_edges=True
        r=yield ent("選取 3D 實體",types=(Solid3D,))
    if not is_pt(r):return
    solid=r[0]
    val=yield num("指定%s距離/半徑" % ("圓角" if opname=="FILLET" else "倒角"),default=1.0)
    if not isinstance(val,(int,float)) or val<=0:return
    try:
        import cadquery as cq
        from .io_utils import _cq_shape_from_solid
        sh=_cq_shape_from_solid(solid,1.0); edges=sh.Edges()
        picked=list(edges)
        if not all_edges:
            sub=getattr(c,"last_subedge",None); idx=sub[1] if sub and sub[0] is solid else None
            if idx is None or idx<0 or idx>=len(solid.edges):
                c.msg("請直接點選實體上的一條可見邊。") ; return
            ia,ib=solid.edges[idx]; a,b=solid.vertices[ia],solid.vertices[ib]; mid=((a[0]+b[0])/2,(a[1]+b[1])/2,(a[2]+b[2])/2)
            pv=cq.Vertex.makeVertex(*mid)
            picked=[min(edges,key=lambda ed:ed.distance(pv))]
        wp=cq.Workplane(obj=sh).newObject(picked)
        res=(wp.fillet(float(val)) if opname=="FILLET" else wp.chamfer(float(val))).val()
        # Workplane may return a Compound containing the resulting solid.
        if hasattr(res,'Solids') and len(res.Solids())==1:res=res.Solids()[0]
        ns=_cq_to_solid(c,res,"FILLETEDGE" if opname=="FILLET" else "CHAMFEREDGE",deflection=0.9)
        if ns:c.replace(solid,ns);c.changed();c.keep_selection([ns])
    except Exception as ex:c.msg(("FILLETEDGE" if opname=="FILLET" else "CHAMFEREDGE")+" 失敗：%s"%ex)

def FILLETEDGE(c):
    yield from _cq_modify_edges(c,"FILLET")
def CHAMFEREDGE(c):
    yield from _cq_modify_edges(c,"CHAMFER")


def MIRROR3D(c):
    ents=yield sel("選取要 3D 鏡射的實體")
    solids=[e for e in ents if isinstance(e,Solid3D)]
    if not solids:return
    plane=yield kwd("指定鏡射平面", (("XY","XY 平面"),("YZ","YZ 平面"),("ZX","ZX 平面")), default="YZ")
    if plane is None:return
    offset=yield num("指定平面偏移", default=0.0)
    if not isinstance(offset,(int,float)):return
    out=[]
    for s in solids:
        vv=[]
        for x,y,z in s.vertices:
            if plane=="XY":z=2*offset-z
            elif plane=="YZ":x=2*offset-x
            else:y=2*offset-y
            vv.append((x,y,z))
        ns=s.clone(vertices=vv,shape="MIRROR3D",brep_b64="")
        try:
            from .io_utils import _cq_shape_from_solid,_shape_to_brep_b64
            bp={"XY":(0,0,float(offset)),"YZ":(float(offset),0,0),"ZX":(0,float(offset),0)}[plane]
            sh=_cq_shape_from_solid(s,1.0).mirror(plane,basePointVector=bp)
            ns.brep_b64=_shape_to_brep_b64(sh)
        except Exception:pass
        c.replace(s,ns); out.append(ns)
    c.changed(); c.keep_selection(out)


def SLICE(c):
    ents=yield sel("選取要切割的 3D 實體")
    solids=[e for e in ents if isinstance(e,Solid3D)]
    if not solids:return
    axis=yield kwd("指定切割平面法向", (("X","X"),("Y","Y"),("Z","Z")), default="Z")
    pos=yield num("指定切割座標",default=0.0)
    side=yield kwd("保留哪一側", (("P","正側"),("N","負側"),("B","兩側")), default="B")
    if axis is None or not isinstance(pos,(int,float)) or side is None:return
    try:
        import cadquery as cq
        from .io_utils import _cq_shape_from_solid
        out=[]
        for s0 in solids:
            sh=_cq_shape_from_solid(s0,1.0);bb=sh.BoundingBox();pad=max(bb.xlen,bb.ylen,bb.zlen,1.0)*2.0
            xmin,xmax=bb.xmin-pad,bb.xmax+pad; ymin,ymax=bb.ymin-pad,bb.ymax+pad; zmin,zmax=bb.zmin-pad,bb.zmax+pad
            p=float(pos)
            def mkbox(x0,x1,y0,y1,z0,z1):
                if x1<=x0 or y1<=y0 or z1<=z0:return None
                return cq.Workplane("XY").box(x1-x0,y1-y0,z1-z0,centered=(True,True,True)).translate(((x0+x1)/2,(y0+y1)/2,(z0+z1)/2)).val()
            if axis=="X":bp=mkbox(p,xmax,ymin,ymax,zmin,zmax);bn=mkbox(xmin,p,ymin,ymax,zmin,zmax)
            elif axis=="Y":bp=mkbox(xmin,xmax,p,ymax,zmin,zmax);bn=mkbox(xmin,xmax,ymin,p,zmin,zmax)
            else:bp=mkbox(xmin,xmax,ymin,ymax,p,zmax);bn=mkbox(xmin,xmax,ymin,ymax,zmin,p)
            pieces=[]
            for want,box,name in ((side in ("P","B"),bp,"SLICE+"),(side in ("N","B"),bn,"SLICE-")):
                if not want or box is None:continue
                q=sh.intersect(box)
                try:vol=q.Volume()
                except Exception:vol=0.0
                if vol>1e-9:
                    ns=_cq_to_solid(c,q,name)
                    if ns:pieces.append(ns)
            if pieces:
                c.replace(s0,pieces);out+=pieces
        if out:c.changed();c.keep_selection(out)
        else:c.msg("SLICE：切割平面沒有穿過所選實體。")
    except Exception as ex:c.msg("SLICE 失敗：%s"%ex)


COMMANDS = {
    "LINE": LINE, "PLINE": PLINE, "CIRCLE": CIRCLE, "ARC": ARC, "RECTANG": RECTANG, "POLYGON": POLYGON,
    "ELLIPSE": ELLIPSE, "SPLINE": SPLINE, "XLINE": XLINE, "RAY": RAY, "POINT": POINT, "TEXT": TEXT, "MTEXT": MTEXT,
    "HATCH": HATCH, "REVCLOUD": REVCLOUD,
    "ERASE": ERASE, "MOVE": MOVE, "COPY": COPY, "ROTATE": ROTATE, "SCALE": SCALE, "MIRROR": MIRROR,
    "OFFSET": OFFSET, "TRIM": TRIM, "EXTEND": EXTEND, "FILLET": FILLET, "CHAMFER": CHAMFER, "STRETCH": STRETCH,
    "ARRAY": ARRAY, "ARRAYRECT": ARRAYRECT, "ARRAYPOLAR": ARRAYPOLAR, "ARRAYEDIT": ARRAYEDIT, "EXPLODE": EXPLODE, "JOIN": JOIN,
    "BREAK": BREAK, "MATCHPROP": MATCHPROP, "DIVIDE": DIVIDE, "MEASURE": MEASURE, "OVERKILL": OVERKILL,
    "DIM": DIM, "DIMLINEAR": DIMLINEAR, "DIMALIGNED": DIMALIGNED, "DIMRADIUS": DIMRADIUS,
    "DIMDIAMETER": DIMDIAMETER, "DIMANGULAR": DIMANGULAR, "MLEADER": MLEADER,
    "BLOCK": BLOCK, "INSERT": INSERT,
    "DIST": DIST, "AREA": AREA, "ID": ID, "LIST": LIST,
    "ZOOM": ZOOM, "REGEN": REGEN, "PAN": PAN,
    "BOX": BOX, "CYLINDER": CYLINDER, "CONE": CONE, "SPHERE": SPHERE, "EXTRUDE": EXTRUDE, "PRESSPULL": PRESSPULL,
    "WEDGE": WEDGE, "PYRAMID": PYRAMID, "TORUS": TORUS, "MOVE3D": MOVE3D, "PLACE3D": PLACE3D, "ROTATE3D": ROTATE3D, "SCALE3D": SCALE3D,
    "UNION": UNION, "SUBTRACT": SUBTRACT, "INTERSECT": INTERSECT,
    "REVOLVE": REVOLVE, "SWEEP": SWEEP, "LOFT": LOFT, "FILLETEDGE": FILLETEDGE, "CHAMFEREDGE": CHAMFEREDGE,
    "MIRROR3D": MIRROR3D, "SLICE": SLICE,
    "LAYOFF": LAYOFF, "LAYFRZ": LAYFRZ, "LAYLCK": LAYLCK, "LAYON": LAYON, "LAYTHW": LAYTHW, "LAYULK": LAYULK,
    "LAYMCUR": LAYMCUR, "LAYISO": LAYISO, "LAYUNISO": LAYUNISO, "SELECTSIMILAR": SELECTSIMILAR, "PURGE": PURGE,
}

ALIASES = {
    "L": "LINE", "PL": "PLINE", "C": "CIRCLE", "A": "ARC", "REC": "RECTANG", "RECTANGLE": "RECTANG",
    "POL": "POLYGON", "EL": "ELLIPSE", "SPL": "SPLINE", "XL": "XLINE", "PO": "POINT", "DT": "TEXT",
    "DTEXT": "TEXT", "T": "MTEXT", "MT": "MTEXT", "H": "HATCH", "BH": "HATCH",
    "E": "ERASE", "M": "MOVE", "CO": "COPY", "CP": "COPY", "RO": "ROTATE", "SC": "SCALE", "MI": "MIRROR",
    "O": "OFFSET", "TR": "TRIM", "EX": "EXTEND", "F": "FILLET", "CHA": "CHAMFER", "S": "STRETCH",
    "AR": "ARRAY", "ARE": "ARRAYEDIT", "X": "EXPLODE", "J": "JOIN", "BR": "BREAK", "MA": "MATCHPROP", "DIV": "DIVIDE", "ME": "MEASURE",
    "DLI": "DIMLINEAR", "DIMLIN": "DIMLINEAR", "DAL": "DIMALIGNED", "DRA": "DIMRADIUS", "DDI": "DIMDIAMETER",
    "DAN": "DIMANGULAR", "MLD": "MLEADER", "LE": "MLEADER", "QLEADER": "MLEADER",
    "B": "BLOCK", "I": "INSERT", "DI": "DIST", "AA": "AREA", "LI": "LIST", "LS": "LIST",
    "Z": "ZOOM", "RE": "REGEN", "P": "PAN", "PU": "PURGE", "EXT": "EXTRUDE",
    "UNI": "UNION", "SU": "SUBTRACT", "IN": "INTERSECT", "3M": "MOVE3D", "3P": "PLACE3D", "3R": "ROTATE3D", "3S": "SCALE3D",
    "REV": "REVOLVE", "SW": "SWEEP", "LO": "LOFT", "FEDGE": "FILLETEDGE", "CEDGE": "CHAMFEREDGE",
}

# 指令行自動完成用的說明
DESCRIPTIONS = {
    "LINE": "線", "PLINE": "聚合線", "CIRCLE": "圓", "ARC": "弧", "RECTANG": "矩形", "POLYGON": "多邊形",
    "ELLIPSE": "橢圓", "SPLINE": "雲形線", "XLINE": "建構線", "RAY": "射線", "POINT": "點", "TEXT": "單行文字",
    "MTEXT": "多行文字", "HATCH": "填充線", "REVCLOUD": "修訂雲形", "ERASE": "刪除", "MOVE": "移動", "COPY": "複製",
    "ROTATE": "旋轉", "SCALE": "比例", "MIRROR": "鏡射", "OFFSET": "偏移", "TRIM": "修剪", "EXTEND": "延伸",
    "FILLET": "圓角", "CHAMFER": "倒角", "STRETCH": "拉伸", "ARRAY": "關聯式陣列", "ARRAYEDIT": "編輯關聯式陣列", "EXPLODE": "分解", "JOIN": "接合",
    "BREAK": "切斷", "MATCHPROP": "複製性質", "DIVIDE": "等分", "MEASURE": "等距", "OVERKILL": "刪除重複物件",
    "DIM": "智慧標註", "DIMLINEAR": "線性標註", "DIMALIGNED": "對齊式標註", "DIMRADIUS": "半徑標註",
    "DIMDIAMETER": "直徑標註", "DIMANGULAR": "角度標註", "MLEADER": "多重引線", "BLOCK": "建立圖塊",
    "INSERT": "插入圖塊", "DIST": "距離", "AREA": "面積", "ID": "點座標", "LIST": "列示", "ZOOM": "縮放",
    "REGEN": "重生", "LAYOFF": "關閉圖層", "LAYFRZ": "凍結圖層", "LAYLCK": "鎖護圖層", "LAYON": "打開所有圖層",
    "LAYTHW": "解凍所有圖層", "LAYULK": "解鎖所有圖層", "LAYMCUR": "設為目前圖層", "LAYISO": "隔離圖層",
    "LAYUNISO": "取消隔離", "SELECTSIMILAR": "選取類似物件", "PURGE": "清除",
    "BOX": "方塊", "CYLINDER": "圓柱體", "CONE": "圓錐體", "SPHERE": "球體", "EXTRUDE": "擠出", "PRESSPULL": "按拉",
    "WEDGE": "楔體", "PYRAMID": "金字塔", "TORUS": "圓環", "MOVE3D": "3D 移動", "PLACE3D": "3D 精準定位", "ROTATE3D": "3D 旋轉", "SCALE3D": "3D 比例",
    "UNION": "聯集", "SUBTRACT": "差集", "INTERSECT": "交集",
    "REVOLVE": "旋轉成實體", "SWEEP": "掃掠", "LOFT": "斷面混成", "FILLETEDGE": "實體邊圓角", "CHAMFEREDGE": "實體邊倒角",
    "MIRROR3D": "3D 鏡射", "SLICE": "切割實體",
}
