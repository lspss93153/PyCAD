# SPDX-License-Identifier: GPL-3.0-only
"""圖面資料模型：圖層、圖元、圖塊、文件。

圖元一律當成「不可變」使用：修改時用 clone()/transformed() 產生新物件再替換，
這樣復原堆疊只要保存清單的淺拷貝即可，大圖也不會卡。
"""
import math
import uuid
from dataclasses import dataclass, field, fields, replace
from . import geometry as G

BYLAYER = 256
BYBLOCK = 0
LW_BYLAYER, LW_BYBLOCK, LW_DEFAULT = -1, -2, -3
TWO_PI = 2 * math.pi

UNIT_NAMES = {0: "無單位", 1: "英吋", 2: "英呎", 3: "英里", 4: "毫米", 5: "公分", 6: "公尺", 7: "公里", 8: "微英吋", 9: "密耳", 10: "碼", 14: "公寸", 15: "公丈"}
UNIT_CODES = {v: k for k, v in UNIT_NAMES.items()}

# ---------------------------------------------------------------- 顏色 (ACI)
_ACI_BASE = {1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255), 5: (0, 0, 255),
             6: (255, 0, 255), 7: (255, 255, 255), 8: (128, 128, 128), 9: (192, 192, 192)}
_ACI_GRAY = {250: 51, 251: 91, 252: 132, 253: 173, 254: 214, 255: 255}
COLOR_NAMES = {1: "紅", 2: "黃", 3: "綠", 4: "青", 5: "藍", 6: "洋紅", 7: "白"}


def aci_rgb(i):
    """AutoCAD 顏色索引 -> (r, g, b)。"""
    if i in _ACI_BASE:
        return _ACI_BASE[i]
    if i in _ACI_GRAY:
        g = _ACI_GRAY[i]
        return (g, g, g)
    if 10 <= i <= 249:
        hue = ((i // 10) - 1) * 15.0
        j = i % 10
        val = (1.0, 0.8, 0.6, 0.5, 0.3)[j // 2]
        sat = 1.0 if j % 2 == 0 else 0.5
        c = val * sat
        x = c * (1 - abs((hue / 60.0) % 2 - 1))
        m = val - c
        r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(hue // 60) % 6]
        return (int(round((r + m) * 255)), int(round((g + m) * 255)), int(round((b + m) * 255)))
    return (255, 255, 255)


def color_name(i):
    if i == BYLAYER:
        return "ByLayer"
    if i == BYBLOCK:
        return "ByBlock"
    return COLOR_NAMES.get(i, "顏色 %d" % i)


# ---------------------------------------------------------------- 線型（公制，單位 mm）
LINETYPES = {
    "Continuous": [],
    "DASHED": [12.7, -6.35],
    "HIDDEN": [6.35, -3.175],
    "CENTER": [31.75, -6.35, 6.35, -6.35],
    "PHANTOM": [31.75, -6.35, 6.35, -6.35, 6.35, -6.35],
    "DASHDOT": [12.7, -6.35, 0, -6.35],
    "DIVIDE": [12.7, -6.35, 0, -6.35, 0, -6.35],
    "BORDER": [12.7, -6.35, 12.7, -6.35, 0, -6.35],
    "DOT": [0, -6.35],
}
LINEWEIGHTS = [0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211]


def lw_name(v):
    return {LW_BYLAYER: "ByLayer", LW_BYBLOCK: "ByBlock", LW_DEFAULT: "預設"}.get(v, "%.2f mm" % (v / 100.0))


@dataclass
class Layer:
    name: str = "0"
    color: int = 7
    ltype: str = "Continuous"
    lw: int = LW_DEFAULT
    on: bool = True
    frozen: bool = False
    locked: bool = False
    plot: bool = True


@dataclass
class Block:
    name: str = ""
    bx: float = 0.0
    by: float = 0.0
    entities: list = field(default_factory=list)


def fmt(v, dec=4):
    """數字格式化：去掉多餘的 0。"""
    s = ("%." + str(dec) + "f") % v
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def text_width(s, h):
    w = 0.0
    for ch in s:
        w += 1.0 if ord(ch) > 0x2E7F else 0.62
    return w * h


# ---------------------------------------------------------------- 圖元基底
@dataclass
class Entity:
    # Stable identity used by associative relationships (for example HATCH -> boundary).
    # clone()/transformed() deliberately preserve it for in-place edits; Canvas.add*
    # refreshes duplicated ids when a real copy is inserted into the document.
    uid: str = field(default_factory=lambda: uuid.uuid4().hex, kw_only=True)
    layer: str = "0"
    color: int = BYLAYER
    # DXF true-color (0xRRGGBB); -1 means use ACI/ByLayer/ByBlock.  Keeping it in
    # the base entity prevents a DXF round-trip from silently degrading RGB colors.
    truecolor: int = -1
    ltype: str = "ByLayer"
    lw: int = LW_BYLAYER
    lts: float = 1.0
    KIND = "ENTITY"
    NAME = "物件"

    def clone(self, **kw):
        return replace(self, **kw)

    def common(self):
        return dict(layer=self.layer, color=self.color, truecolor=self.truecolor, ltype=self.ltype, lw=self.lw, lts=self.lts)

    def to_dict(self):
        d = {"type": self.KIND}
        for f in fields(self):
            d[f.name] = getattr(self, f.name)
        return d

    def prims(self):
        c = self.__dict__.get("_prims")
        if c is None:
            c = self._prims_()
            self.__dict__["_prims"] = c
        return c

    def _prims_(self):
        return []

    def bbox(self):
        c = self.__dict__.get("_bbox")
        if c is None:
            c = self._bbox_()
            self.__dict__["_bbox"] = c
        return c

    def _bbox_(self):
        bs = [G.prim_bbox(p) for p in self.prims()]
        if not bs:
            return None
        return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))

    def transformed(self, m):
        return self

    def snaps(self):
        return []

    def grips(self):
        return []

    def grip_moved(self, i, p):
        return self

    def def_points(self):
        """拉伸 (STRETCH) 用的定義點。"""
        return self.grips()


@dataclass
class Line(Entity):
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    KIND = "LINE"
    NAME = "線"

    def _prims_(self):
        return [('L', self.x1, self.y1, self.x2, self.y2)]

    def transformed(self, m):
        a, b = G.m_apply(m, (self.x1, self.y1)), G.m_apply(m, (self.x2, self.y2))
        return self.clone(x1=a[0], y1=a[1], x2=b[0], y2=b[1])

    def snaps(self):
        return [("END", self.x1, self.y1), ("END", self.x2, self.y2),
                ("MID", (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)]

    def grips(self):
        return [(self.x1, self.y1), ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2), (self.x2, self.y2)]

    def grip_moved(self, i, p):
        if i == 0:
            return self.clone(x1=p[0], y1=p[1])
        if i == 2:
            return self.clone(x2=p[0], y2=p[1])
        g = self.grips()[1]
        return self.transformed(G.m_translate(p[0] - g[0], p[1] - g[1]))

    def def_points(self):
        return [(self.x1, self.y1), (self.x2, self.y2)]

    def length(self):
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)


@dataclass
class Circle(Entity):
    cx: float = 0.0
    cy: float = 0.0
    r: float = 1.0
    KIND = "CIRCLE"
    NAME = "圓"

    def _prims_(self):
        return [('A', self.cx, self.cy, self.r, 0.0, 360.0)]

    def _bbox_(self):
        return (self.cx - self.r, self.cy - self.r, self.cx + self.r, self.cy + self.r)

    def transformed(self, m):
        s, rot, mir, uni = G.m_info(m)
        c = G.m_apply(m, (self.cx, self.cy))
        if uni:
            return self.clone(cx=c[0], cy=c[1], r=self.r * s)
        ma, ratio, _, _ = G.ellipse_axes(G.m_vec(m, (self.r, 0)), G.m_vec(m, (0, self.r)))
        return Ellipse(cx=c[0], cy=c[1], mx=ma[0], my=ma[1], ratio=ratio, **self.common())

    def snaps(self):
        c, r = (self.cx, self.cy), self.r
        return [("CEN", c[0], c[1])] + [("QUA",) + G.polar(c, a, r) for a in (0, 90, 180, 270)]

    def grips(self):
        c, r = (self.cx, self.cy), self.r
        return [c] + [G.polar(c, a, r) for a in (0, 90, 180, 270)]

    def grip_moved(self, i, p):
        if i == 0:
            return self.clone(cx=p[0], cy=p[1])
        r = G.dist((self.cx, self.cy), p)
        return self.clone(r=r) if r > G.EPS else self

    def def_points(self):
        return [(self.cx, self.cy)]


@dataclass
class Arc(Entity):
    cx: float = 0.0
    cy: float = 0.0
    r: float = 1.0
    a0: float = 0.0
    a1: float = 90.0
    KIND = "ARC"
    NAME = "弧"

    def span(self):
        s = (self.a1 - self.a0) % 360.0
        return s if s > 1e-9 else 360.0

    def _prims_(self):
        return [('A', self.cx, self.cy, self.r, self.a0 % 360.0, self.span())]

    def ends(self):
        c = (self.cx, self.cy)
        return G.polar(c, self.a0, self.r), G.polar(c, self.a0 + self.span(), self.r)

    def midpoint(self):
        return G.polar((self.cx, self.cy), self.a0 + self.span() / 2, self.r)

    def transformed(self, m):
        s, rot, mir, uni = G.m_info(m)
        c = G.m_apply(m, (self.cx, self.cy))
        p, q = self.ends()
        if uni:
            p, q = G.m_apply(m, p), G.m_apply(m, q)
            if mir:
                p, q = q, p
            return self.clone(cx=c[0], cy=c[1], r=self.r * s, a0=G.ang(c, p), a1=G.ang(c, q))
        ma, ratio, shift, flip = G.ellipse_axes(G.m_vec(m, (self.r, 0)), G.m_vec(m, (0, self.r)))
        t0, t1 = math.radians(self.a0) - shift, math.radians(self.a0 + self.span()) - shift
        if flip:
            t0, t1 = -t1, -t0
        return Ellipse(cx=c[0], cy=c[1], mx=ma[0], my=ma[1], ratio=ratio, t0=t0 % TWO_PI, t1=t1 % TWO_PI,
                       **self.common())

    def snaps(self):
        p, q = self.ends()
        mp = self.midpoint()
        out = [("END", p[0], p[1]), ("END", q[0], q[1]), ("MID", mp[0], mp[1]), ("CEN", self.cx, self.cy)]
        for a in (0, 90, 180, 270):
            if G.on_arc(a, self.a0 % 360.0, self.span()):
                out.append(("QUA",) + G.polar((self.cx, self.cy), a, self.r))
        return out

    def grips(self):
        p, q = self.ends()
        return [p, self.midpoint(), q, (self.cx, self.cy)]

    def grip_moved(self, i, p):
        if i == 3:
            return self.clone(cx=p[0], cy=p[1])
        g = self.grips()[:3]
        g[i] = p
        a = G.arc_3p(g[0], g[1], g[2])
        if a is None:
            return self
        return self.clone(cx=a[0], cy=a[1], r=a[2], a0=a[3], a1=a[4])

    def def_points(self):
        p, q = self.ends()
        return [p, q, (self.cx, self.cy)]

    def length(self):
        return self.r * math.radians(self.span())


@dataclass
class Polyline(Entity):
    pts: list = field(default_factory=list)      # [(x, y, bulge), ...]
    closed: bool = False
    # LWPOLYLINE geometric width. const_width is DXF group 43; widths stores
    # per-vertex (start_width, end_width) pairs so import/export can round-trip.
    const_width: float = 0.0
    widths: list = field(default_factory=list)
    KIND = "LWPOLYLINE"
    NAME = "聚合線"

    def _prims_(self):
        return G.poly_prims(self.pts, self.closed)

    def transformed(self, m):
        s, rot, mir, uni = G.m_info(m)
        wscale = abs(float(s))
        widths = [(float(a) * wscale, float(b) * wscale) for a, b in self.widths]
        if uni or all(abs(p[2]) < 1e-12 for p in self.pts):
            sg = -1.0 if mir else 1.0
            return self.clone(pts=[G.m_apply(m, p) + (p[2] * sg,) for p in self.pts],
                              const_width=abs(self.const_width) * wscale, widths=widths)
        flat = G.flatten_prims(self.prims())
        if self.closed and len(flat) > 1 and G.dist(flat[0], flat[-1]) < 1e-9:
            flat = flat[:-1]
        # Non-uniform transforms cannot retain a true constant/segment width.  Keep
        # the centerline exact and conservatively scale width by the mean factor.
        return self.clone(pts=[G.m_apply(m, p) + (0.0,) for p in flat],
                          const_width=abs(self.const_width) * wscale, widths=widths)

    def _bbox_(self):
        b = super()._bbox_()
        if b is None:
            return None
        widths = [abs(float(self.const_width))]
        widths += [abs(float(x)) for pair in self.widths for x in pair]
        pad = (max(widths) if widths else 0.0) * 0.5
        return (b[0]-pad, b[1]-pad, b[2]+pad, b[3]+pad) if pad > 0 else b

    def snaps(self):
        out = [("END", p[0], p[1]) for p in self.pts]
        for pr in self.prims():
            q = G.prim_point(pr, G.prim_len(pr) / 2)
            out.append(("MID", q[0], q[1]))
            if pr[0] == 'A':
                out.append(("CEN", pr[1], pr[2]))
        if self.closed and len(self.pts) >= 3:
            c = self.centroid()
            out.append(("GCE", c[0], c[1]))
        return out

    def centroid(self):
        pts = G.flatten_prims(self.prims())
        a = G.poly_area(pts)
        if abs(a) < G.EPS:
            return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        cx = cy = 0.0
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            k = x1 * y2 - x2 * y1
            cx += (x1 + x2) * k
            cy += (y1 + y2) * k
        return (cx / (6 * a), cy / (6 * a))

    def grips(self):
        return [(p[0], p[1]) for p in self.pts]

    def grip_moved(self, i, p):
        pts = list(self.pts)
        pts[i] = (p[0], p[1], pts[i][2])
        return self.clone(pts=pts)

    def length(self):
        return sum(G.prim_len(p) for p in self.prims())

    def area(self):
        return abs(G.poly_area(G.flatten_prims(self.prims(), 2.0)))


@dataclass
class Ellipse(Entity):
    cx: float = 0.0
    cy: float = 0.0
    mx: float = 1.0          # 長軸向量
    my: float = 0.0
    ratio: float = 0.5
    t0: float = 0.0
    t1: float = TWO_PI
    KIND = "ELLIPSE"
    NAME = "橢圓"

    def full(self):
        s = (self.t1 - self.t0) % TWO_PI
        return s < 1e-9 or s > TWO_PI - 1e-9

    def points(self):
        c = self.__dict__.get("_pts")
        if c is None:
            c = G.ellipse_points(self.cx, self.cy, self.mx, self.my, self.ratio, self.t0, self.t1)
            self.__dict__["_pts"] = c
        return c

    def _prims_(self):
        p = self.points()
        return [('L', p[i][0], p[i][1], p[i + 1][0], p[i + 1][1]) for i in range(len(p) - 1)]

    def at(self, t):
        nx, ny = -self.my * self.ratio, self.mx * self.ratio
        return (self.cx + self.mx * math.cos(t) + nx * math.sin(t), self.cy + self.my * math.cos(t) + ny * math.sin(t))

    def transformed(self, m):
        c = G.m_apply(m, (self.cx, self.cy))
        u = G.m_vec(m, (self.mx, self.my))
        v = G.m_vec(m, (-self.my * self.ratio, self.mx * self.ratio))
        ma, ratio, shift, flip = G.ellipse_axes(u, v)
        if self.full():
            return self.clone(cx=c[0], cy=c[1], mx=ma[0], my=ma[1], ratio=ratio, t0=0.0, t1=TWO_PI)
        span = (self.t1 - self.t0) % TWO_PI
        t0, t1 = self.t0 - shift, self.t0 + span - shift
        if flip:
            t0, t1 = -t1, -t0
        return self.clone(cx=c[0], cy=c[1], mx=ma[0], my=ma[1], ratio=ratio, t0=t0 % TWO_PI, t1=t1 % TWO_PI)

    def snaps(self):
        out = [("CEN", self.cx, self.cy)]
        if self.full():
            out += [("QUA",) + self.at(t) for t in (0, math.pi / 2, math.pi, 3 * math.pi / 2)]
        else:
            p = self.points()
            out += [("END", p[0][0], p[0][1]), ("END", p[-1][0], p[-1][1])]
        return out

    def grips(self):
        return [(self.cx, self.cy)] + [self.at(t) for t in (0, math.pi / 2, math.pi, 3 * math.pi / 2)]

    def grip_moved(self, i, p):
        if i == 0:
            return self.clone(cx=p[0], cy=p[1])
        d = G.dist((self.cx, self.cy), p)
        major = math.hypot(self.mx, self.my)
        if d < G.EPS or major < G.EPS:
            return self
        if i in (1, 3):
            minor = major * self.ratio
            if d < minor:
                return self
            k = d / major
            return self.clone(mx=self.mx * k, my=self.my * k, ratio=minor / d)
        return self.clone(ratio=min(1.0, d / major))

    def def_points(self):
        return [(self.cx, self.cy)]


@dataclass
class Spline(Entity):
    fit: list = field(default_factory=list)
    ctrl: list = field(default_factory=list)
    knots: list = field(default_factory=list)
    degree: int = 3
    closed: bool = False
    KIND = "SPLINE"
    NAME = "雲形線"

    def points(self):
        c = self.__dict__.get("_pts")
        if c is None:
            if self.ctrl:
                c = G.bspline_points(self.ctrl, self.knots, self.degree)
            else:
                c = G.catmull_rom(self.fit, self.closed)
            self.__dict__["_pts"] = c
        return c

    def _prims_(self):
        p = self.points()
        return [('L', p[i][0], p[i][1], p[i + 1][0], p[i + 1][1]) for i in range(len(p) - 1)]

    def transformed(self, m):
        return self.clone(fit=[G.m_apply(m, p) for p in self.fit], ctrl=[G.m_apply(m, p) for p in self.ctrl])

    def snaps(self):
        p = self.points()
        if not p:
            return []
        return [("END", p[0][0], p[0][1]), ("END", p[-1][0], p[-1][1])]

    def grips(self):
        return [(p[0], p[1]) for p in (self.fit or self.ctrl)]

    def grip_moved(self, i, p):
        if self.fit:
            f = list(self.fit)
            f[i] = (p[0], p[1])
            return self.clone(fit=f)
        c = list(self.ctrl)
        c[i] = (p[0], p[1])
        return self.clone(ctrl=c)


@dataclass
class Point(Entity):
    x: float = 0.0
    y: float = 0.0
    KIND = "POINT"
    NAME = "點"

    def _bbox_(self):
        return (self.x, self.y, self.x, self.y)

    def transformed(self, m):
        p = G.m_apply(m, (self.x, self.y))
        return self.clone(x=p[0], y=p[1])

    def snaps(self):
        return [("NOD", self.x, self.y)]

    def grips(self):
        return [(self.x, self.y)]

    def grip_moved(self, i, p):
        return self.clone(x=p[0], y=p[1])


@dataclass
class Text(Entity):
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    height: float = 2.5
    rot: float = 0.0
    halign: int = 0      # 0 左 1 中 2 右
    valign: int = 0      # 0 基準線 1 下 2 中 3 上
    KIND = "TEXT"
    NAME = "文字"

    def corners(self):
        w = text_width(self.text, self.height)
        h = self.height
        x0 = -w * self.halign / 2.0
        y0 = {0: 0.0, 1: 0.0, 2: -h / 2.0, 3: -h}.get(self.valign, 0.0)
        m = G.m_rotate((0, 0), self.rot)
        return [(self.x + q[0], self.y + q[1]) for q in
                (G.m_apply(m, c) for c in ((x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)))]

    def _bbox_(self):
        c = self.corners()
        return (min(p[0] for p in c), min(p[1] for p in c), max(p[0] for p in c), max(p[1] for p in c))

    def transformed(self, m):
        s, rot, mir, uni = G.m_info(m)
        p = G.m_apply(m, (self.x, self.y))
        d = G.m_vec(m, (math.cos(math.radians(self.rot)), math.sin(math.radians(self.rot))))
        a = math.degrees(math.atan2(d[1], d[0]))
        hs = math.hypot(m[2], m[3])
        if mir:
            return self.clone(x=p[0], y=p[1], height=self.height * hs, rot=(a + 180.0) % 360.0,
                              halign=2 - self.halign)
        return self.clone(x=p[0], y=p[1], height=self.height * hs, rot=a % 360.0)

    def snaps(self):
        return [("INS", self.x, self.y)]

    def grips(self):
        return [(self.x, self.y)]

    def grip_moved(self, i, p):
        return self.clone(x=p[0], y=p[1])


@dataclass
class MText(Entity):
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    height: float = 2.5
    rot: float = 0.0
    width: float = 0.0
    attach: int = 1      # 1 左上 2 中上 3 右上 4 左中 5 正中 6 右中 7 左下 8 中下 9 右下
    KIND = "MTEXT"
    NAME = "多行文字"

    def lines(self):
        out = []
        for ln in self.text.split("\n"):
            if self.width > 0 and text_width(ln, self.height) > self.width:
                cur = ""
                for ch in ln:
                    if cur and text_width(cur + ch, self.height) > self.width:
                        out.append(cur)
                        cur = ch.lstrip() if ch == " " else ch
                    else:
                        cur += ch
                out.append(cur)
            else:
                out.append(ln)
        return out or [""]

    def layout(self):
        """回傳 [(dx, dy, 字串)]：每一行基準線相對插入點（未旋轉）的位置。"""
        ls = self.lines()
        h = self.height
        step = h * 5.0 / 3.0
        total = h + step * (len(ls) - 1)
        wmax = max([text_width(s, h) for s in ls] + [self.width if self.width > 0 else 0.0])
        col, row = (self.attach - 1) % 3, (self.attach - 1) // 3
        top = {0: 0.0, 1: total / 2.0, 2: total}[row]
        out = []
        for i, s in enumerate(ls):
            w = text_width(s, h)
            dx = {0: 0.0, 1: -w / 2.0, 2: -w}[col]
            out.append((dx, top - h - i * step, s))
        return out, wmax, total, col, top

    def corners(self):
        _, wmax, total, col, top = self.layout()
        x0 = {0: 0.0, 1: -wmax / 2.0, 2: -wmax}[col]
        m = G.m_rotate((0, 0), self.rot)
        return [(self.x + q[0], self.y + q[1]) for q in
                (G.m_apply(m, c) for c in ((x0, top - total), (x0 + wmax, top - total), (x0 + wmax, top), (x0, top)))]

    def _bbox_(self):
        c = self.corners()
        return (min(p[0] for p in c), min(p[1] for p in c), max(p[0] for p in c), max(p[1] for p in c))

    def transformed(self, m):
        s, rot, mir, uni = G.m_info(m)
        p = G.m_apply(m, (self.x, self.y))
        d = G.m_vec(m, (math.cos(math.radians(self.rot)), math.sin(math.radians(self.rot))))
        a = math.degrees(math.atan2(d[1], d[0]))
        hs = math.hypot(m[2], m[3])
        att = self.attach
        if mir:
            a += 180.0
            att = (att - 1) // 3 * 3 + (2 - (att - 1) % 3) + 1
        return self.clone(x=p[0], y=p[1], height=self.height * hs, width=self.width * hs, rot=a % 360.0, attach=att)

    def snaps(self):
        return [("INS", self.x, self.y)]

    def grips(self):
        return [(self.x, self.y)]

    def grip_moved(self, i, p):
        return self.clone(x=p[0], y=p[1])


@dataclass
class Hatch(Entity):
    loops: list = field(default_factory=list)     # display/containment polygons
    # Stable uid groups of source boundary entities.  Empty means non-associative
    # (e.g. a point-picked traced boundary that cannot be mapped unambiguously).
    boundary_uids: list = field(default_factory=list)
    # Optional exact 2D boundary primitives per loop.  Keeping arcs here prevents a
    # circular DXF hatch boundary from degrading into a many-sided polygon.
    loop_prims: list = field(default_factory=list)
    pattern: str = "SOLID"
    scale: float = 1.0
    angle: float = 0.0
    KIND = "HATCH"
    NAME = "填充線"

    def _prims_(self):
        if self.loop_prims:
            return [tuple(pr) for lp in self.loop_prims for pr in lp]
        out = []
        for lp in self.loops:
            n = len(lp)
            for i in range(n):
                a, b = lp[i], lp[(i + 1) % n]
                out.append(('L', a[0], a[1], b[0], b[1]))
        return out

    def contains(self, p):
        return sum(1 for lp in self.loops if G.point_in_poly(p, lp)) % 2 == 1

    def transformed(self, m):
        s, rot, mir, uni = G.m_info(m)
        lp2=[]
        if self.loop_prims:
            for lp in self.loop_prims:
                q=[]
                for pr0 in lp:
                    pr=tuple(pr0)
                    if pr[0]=='L':
                        a=G.m_apply(m,(pr[1],pr[2]));b=G.m_apply(m,(pr[3],pr[4]));q.append(('L',a[0],a[1],b[0],b[1]))
                    elif pr[0]=='A' and uni:
                        a=Arc(cx=pr[1],cy=pr[2],r=pr[3],a0=pr[4],a1=(pr[4]+pr[5])%360.0).transformed(m)
                        if isinstance(a,Arc):q.extend(a.prims())
                    else:
                        pts=G.flatten_prims([pr],4.0);
                        for i in range(len(pts)-1):
                            a=G.m_apply(m,pts[i]);b=G.m_apply(m,pts[i+1]);q.append(('L',a[0],a[1],b[0],b[1]))
                lp2.append(q)
        return self.clone(loops=[[G.m_apply(m, p) for p in lp] for lp in self.loops], loop_prims=lp2,
                          scale=self.scale * abs(s), angle=(self.angle + rot) % 360.0)

    def def_points(self):
        return [p for lp in self.loops for p in lp]

    def area(self):
        """Area with orientation-independent island handling.

        DXF/HATCH loops are not required to use opposite winding for holes.  Determine
        each loop's nesting depth geometrically and alternate add/subtract by parity,
        so a same-direction circular island is still subtracted from its outer loop.
        """
        loops=[lp for lp in self.loops if len(lp)>=3]
        if not loops:return 0.0
        info=[]
        for lp in loops:
            a=abs(G.poly_area(lp))
            if a<=G.EPS:continue
            # Polygon centroid when possible; average is a safe fallback for malformed loops.
            sa=G.poly_area(lp);cx=cy=0.0
            if abs(sa)>G.EPS:
                acc=0.0
                for p0,p1 in zip(lp,lp[1:]+lp[:1]):
                    cr=p0[0]*p1[1]-p1[0]*p0[1];acc+=cr
                    cx+=(p0[0]+p1[0])*cr;cy+=(p0[1]+p1[1])*cr
                if abs(acc)>G.EPS:
                    cx/=3.0*acc;cy/=3.0*acc
                else:cx=sum(q[0] for q in lp)/len(lp);cy=sum(q[1] for q in lp)/len(lp)
            else:cx=sum(q[0] for q in lp)/len(lp);cy=sum(q[1] for q in lp)/len(lp)
            rep=(cx,cy)
            if not G.point_in_poly(rep,lp):
                # Concave polygons can have a centroid outside. Pull a sample from the
                # first vertex toward the average until it lies inside.
                avg=(sum(q[0] for q in lp)/len(lp),sum(q[1] for q in lp)/len(lp))
                for t in (0.5,0.25,0.1,0.01):
                    q=(lp[0][0]*(1-t)+avg[0]*t,lp[0][1]*(1-t)+avg[1]*t)
                    if G.point_in_poly(q,lp):rep=q;break
            info.append((a,lp,rep))
        total=0.0
        for a,lp,rep in info:
            depth=sum(1 for oa,ol,_ in info if oa>a+G.EPS and G.point_in_poly(rep,ol))
            total += a if depth%2==0 else -a
        return max(0.0,total)


@dataclass
class XLine(Entity):
    x: float = 0.0
    y: float = 0.0
    dx: float = 1.0
    dy: float = 0.0
    ray: bool = False
    KIND = "XLINE"
    NAME = "建構線"
    FAR = 1.0e7

    def _prims_(self):
        L = math.hypot(self.dx, self.dy) or 1.0
        ux, uy = self.dx / L * self.FAR, self.dy / L * self.FAR
        if self.ray:
            return [('L', self.x, self.y, self.x + ux, self.y + uy)]
        return [('L', self.x - ux, self.y - uy, self.x + ux, self.y + uy)]

    def _bbox_(self):
        return None

    def transformed(self, m):
        p = G.m_apply(m, (self.x, self.y))
        d = G.m_vec(m, (self.dx, self.dy))
        return self.clone(x=p[0], y=p[1], dx=d[0], dy=d[1])

    def snaps(self):
        return [("NOD", self.x, self.y)] if not self.ray else [("END", self.x, self.y)]

    def grips(self):
        L = math.hypot(self.dx, self.dy) or 1.0
        return [(self.x, self.y), (self.x + self.dx / L * 10, self.y + self.dy / L * 10)]

    def grip_moved(self, i, p):
        if i == 0:
            return self.clone(x=p[0], y=p[1])
        if G.dist((self.x, self.y), p) < G.EPS:
            return self
        return self.clone(dx=p[0] - self.x, dy=p[1] - self.y)

    def def_points(self):
        return [(self.x, self.y)]


@dataclass
class Dim(Entity):
    kind: str = "LIN"     # LIN 線性 / ALI 對齊 / RAD 半徑 / DIA 直徑 / ANG 角度 / LDR 引線
    pts: list = field(default_factory=list)
    text: str = ""        # 空字串 = 量測值
    th: float = 2.5
    asz: float = 2.5
    dec: int = 2
    rot: float = 0.0
    KIND = "DIMENSION"
    NAME = "標註"

    def transformed(self, m):
        s, rot, mir, uni = G.m_info(m)
        r = self.rot
        if self.kind == "LIN":
            d = G.m_vec(m, (math.cos(math.radians(r)), math.sin(math.radians(r))))
            r = math.degrees(math.atan2(d[1], d[0])) % 180.0
        return self.clone(pts=[G.m_apply(m, p) for p in self.pts], th=self.th * s, asz=self.asz * s, rot=r)

    def measure(self):
        p = self.pts
        k = self.kind
        if k == "ALI":
            return G.dist(p[0], p[1])
        if k == "LIN":
            u = (math.cos(math.radians(self.rot)), math.sin(math.radians(self.rot)))
            return abs((p[1][0] - p[0][0]) * u[0] + (p[1][1] - p[0][1]) * u[1])
        if k == "RAD":
            return G.dist(p[0], p[1])
        if k == "DIA":
            return 2 * G.dist(p[0], p[1])
        if k == "ANG":
            a1, a2, al = G.ang(p[0], p[1]), G.ang(p[0], p[2]), G.ang(p[0], p[3])
            s = (a2 - a1) % 360.0
            return s if (al - a1) % 360.0 <= s else 360.0 - s
        return 0.0

    def label(self):
        if self.kind == "LDR":
            return self.text
        v = self.measure()
        s = {"RAD": "R", "DIA": "Ø"}.get(self.kind, "") + fmt(v, self.dec) + ("°" if self.kind == "ANG" else "")
        if self.text:
            return self.text.replace("<>", s)
        return s

    def parts(self):
        c = self.__dict__.get("_parts")
        if c is None:
            c = _dim_parts(self)
            self.__dict__["_parts"] = c
        return c

    def _prims_(self):
        return [p for e in self.parts() for p in e.prims()]

    def _bbox_(self):
        return _merge_boxes([e.bbox() for e in self.parts()])

    def snaps(self):
        return [("END", p[0], p[1]) for p in self.pts]

    def grips(self):
        return [(p[0], p[1]) for p in self.pts]

    def grip_moved(self, i, p):
        pts = list(self.pts)
        pts[i] = (p[0], p[1])
        if self.kind in ("RAD", "DIA") and i == 2:
            r = G.dist(pts[0], pts[1])
            if G.dist(pts[0], p) > G.EPS:
                pts[1] = G.polar(pts[0], G.ang(pts[0], p), r)
        return self.clone(pts=pts)


@dataclass
class Insert(Entity):
    name: str = ""
    x: float = 0.0
    y: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    rot: float = 0.0
    KIND = "INSERT"
    NAME = "圖塊參考"

    def matrix(self, block):
        m = G.m_translate(-block.bx, -block.by)
        m = G.m_mul(G.m_scale((0, 0), self.sx, self.sy), m)
        m = G.m_mul(G.m_rotate((0, 0), self.rot), m)
        return G.m_mul(G.m_translate(self.x, self.y), m)

    def transformed(self, m):
        r = math.radians(self.rot)
        co, si = math.cos(r), math.sin(r)
        loc = (co * self.sx, si * self.sx, -si * self.sy, co * self.sy, self.x, self.y)
        a, b, c, d, e, f = G.m_mul(m, loc)
        sx = math.hypot(a, b)
        det = a * d - b * c
        sy = det / sx if sx > G.EPS else self.sy
        return self.clone(x=e, y=f, sx=sx, sy=sy, rot=math.degrees(math.atan2(b, a)) % 360.0)

    def snaps(self):
        return [("INS", self.x, self.y)]

    def grips(self):
        return [(self.x, self.y)]

    def grip_moved(self, i, p):
        return self.clone(x=p[0], y=p[1])


@dataclass
class Array(Entity):
    source: list = field(default_factory=list)
    mode: str = "RECT"
    rows: int = 1
    cols: int = 1
    dx: float = 10.0
    dy: float = 10.0
    # Rectangular array spacing is stored as two vectors, not only world-X/world-Y
    # scalars.  This preserves spacing direction after ROTATE/SCALE/MIRROR.
    col_vec: tuple = (0.0, 0.0)
    row_vec: tuple = (0.0, 0.0)
    cx: float = 0.0
    cy: float = 0.0
    count: int = 1
    fill: float = 360.0
    rotate_items: bool = True
    KIND = "ARRAY"
    NAME = "關聯式陣列"

    def to_dict(self):
        d = super().to_dict()
        d["source"] = [e.to_dict() for e in self.source]
        return d

    MAX_EXPANDED_ITEMS = 20000

    def expanded_count(self, limit=None, _depth=0):
        """Estimate leaf count recursively, stopping before pathological nesting."""
        lim=int(limit or self.MAX_EXPANDED_ITEMS)
        if _depth>12:return lim+1
        own=max(1,int(self.count)) if self.mode.upper()=="POLAR" else max(1,int(self.rows))*max(1,int(self.cols))
        per=0
        for e in self.source:
            if isinstance(e,Array):
                n=e.expanded_count(max(1,lim//max(1,own)),_depth+1)
            else:n=1
            per+=n
            if per*own>lim:return lim+1
        return per*own

    def parts(self):
        cached = self.__dict__.get("_parts_cache")
        if cached is not None:
            return cached
        src = list(self.source)
        if not src:
            return []
        if self.expanded_count(self.MAX_EXPANDED_ITEMS)>self.MAX_EXPANDED_ITEMS:
            self.__dict__["_expansion_blocked"]=True
            self.__dict__["_parts_cache"]=[]
            return []
        out = []
        if self.mode.upper() == "POLAR":
            n = max(1, int(self.count))
            step = self.fill / n if abs(abs(self.fill) - 360.0) < 1e-9 else (self.fill / max(1, n - 1))
            b = _merge_boxes([e.bbox() for e in src]) or (0.0, 0.0, 0.0, 0.0)
            ctr = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
            for i in range(n):
                if i == 0:
                    m = G.m_translate(0.0, 0.0)
                elif self.rotate_items:
                    m = G.m_rotate((self.cx, self.cy), step * i)
                else:
                    t = G.m_apply(G.m_rotate((self.cx, self.cy), step * i), ctr)
                    m = G.m_translate(t[0] - ctr[0], t[1] - ctr[1])
                out.extend(e.transformed(m) for e in src)
        else:
            cv = self.col_vec if any(abs(float(v)) > G.EPS for v in self.col_vec) else (float(self.dx), 0.0)
            rv = self.row_vec if any(abs(float(v)) > G.EPS for v in self.row_vec) else (0.0, float(self.dy))
            for i in range(max(1, int(self.rows))):
                for j in range(max(1, int(self.cols))):
                    m = G.m_translate(j * cv[0] + i * rv[0], j * cv[1] + i * rv[1])
                    out.extend(e.transformed(m) for e in src)
        # Cache expanded members; Array entities are treated immutably throughout the model.
        self.__dict__["_parts_cache"] = out
        return out

    def _bbox_(self):
        return _merge_boxes([e.bbox() for e in self.parts()])

    def snaps(self):
        b = self._bbox_()
        if not b:
            return []
        return [("END", b[0], b[1]), ("END", b[2], b[3]), ("MID", (b[0]+b[2])/2, (b[1]+b[3])/2)]

    def _source_center(self):
        b = _merge_boxes([e.bbox() for e in self.source])
        if b:return ((b[0]+b[2])/2.0,(b[1]+b[3])/2.0)
        # INSERT geometry needs Document.block context for a bbox; its insertion point
        # is nevertheless the correct array origin for imported DXF MINSERT objects.
        pts=[(float(e.x),float(e.y)) for e in self.source if isinstance(e,Insert)]
        return (sum(p[0] for p in pts)/len(pts),sum(p[1] for p in pts)/len(pts)) if pts else (0.0,0.0)

    def grips(self):
        if not self.source:
            return []
        o = self._source_center()
        if self.mode.upper() == "POLAR":
            # center / first item center / last item center.  These are meaningful
            # parametric grips instead of arbitrary axis-aligned bbox corners.
            n=max(1,int(self.count)); step=self.fill/n if abs(abs(self.fill)-360.0)<1e-9 else self.fill/max(1,n-1)
            last=G.m_apply(G.m_rotate((self.cx,self.cy), step*max(0,n-1)), o)
            return [(self.cx,self.cy), o, last]
        cv = self.col_vec if any(abs(float(v)) > G.EPS for v in self.col_vec) else (float(self.dx), 0.0)
        rv = self.row_vec if any(abs(float(v)) > G.EPS for v in self.row_vec) else (0.0, float(self.dy))
        return [o, (o[0]+cv[0]*max(0,self.cols-1), o[1]+cv[1]*max(0,self.cols-1)),
                (o[0]+rv[0]*max(0,self.rows-1), o[1]+rv[1]*max(0,self.rows-1))]

    def grip_moved(self, i, p):
        if not self.source:
            return self
        o=self._source_center()
        if self.mode.upper() == "POLAR":
            if i == 0:
                # Move the whole associative array, including its center.
                return self.transformed(G.m_translate(p[0]-self.cx,p[1]-self.cy))
            if i == 1:
                # Change array radius while preserving source shape and angular params.
                vx,vy=o[0]-self.cx,o[1]-self.cy; L=math.hypot(vx,vy)
                nvx,nvy=p[0]-self.cx,p[1]-self.cy; NL=math.hypot(nvx,nvy)
                if L < G.EPS or NL < G.EPS:return self
                # Grip location is the desired new center of the first item.
                return self.clone(source=[e.transformed(G.m_translate(p[0]-o[0],p[1]-o[1])) for e in self.source])
            if i == 2:
                a0=G.ang((self.cx,self.cy),o); a1=G.ang((self.cx,self.cy),p)
                d=(a1-a0)%360.0
                if self.fill<0:d=d-360.0 if d>0 else d
                return self.clone(fill=float(d if abs(d)>G.EPS else self.fill))
            return self
        cv = self.col_vec if any(abs(float(v)) > G.EPS for v in self.col_vec) else (float(self.dx), 0.0)
        rv = self.row_vec if any(abs(float(v)) > G.EPS for v in self.row_vec) else (0.0, float(self.dy))
        if i == 0:
            return self.transformed(G.m_translate(p[0]-o[0],p[1]-o[1]))
        if i == 1 and self.cols > 1:
            n=float(self.cols-1); nv=((p[0]-o[0])/n,(p[1]-o[1])/n)
            return self.clone(col_vec=nv,dx=math.hypot(*nv))
        if i == 2 and self.rows > 1:
            n=float(self.rows-1); nv=((p[0]-o[0])/n,(p[1]-o[1])/n)
            return self.clone(row_vec=nv,dy=math.hypot(*nv))
        return self

    def transformed(self, m):
        src = [e.transformed(m) for e in self.source]
        c = G.m_apply(m, (self.cx, self.cy))
        cv0 = self.col_vec if any(abs(float(v)) > G.EPS for v in self.col_vec) else (float(self.dx), 0.0)
        rv0 = self.row_vec if any(abs(float(v)) > G.EPS for v in self.row_vec) else (0.0, float(self.dy))
        cv = G.m_vec(m, cv0)
        rv = G.m_vec(m, rv0)
        _, _, mirrored, _ = G.m_info(m)
        return self.clone(source=src, cx=c[0], cy=c[1], col_vec=cv, row_vec=rv,
                          dx=math.hypot(*cv), dy=math.hypot(*rv),
                          fill=(-self.fill if mirrored and self.mode.upper()=="POLAR" else self.fill))



@dataclass
class Solid3D(Entity):
    """輕量 3D 實體／線框物件。

    v0.6 的 3D 核心先以頂點、邊與面保存幾何，讓 BOX/CYLINDER/SPHERE/CONE/EXTRUDE
    可以真正儲存 Z 座標，而不是把等角圖炸成一般 2D 線段。後續布林與 ACIS/SAT 核心可在
    不破壞既有 .pycad 圖面的前提下替換內部實體引擎。
    """
    vertices: list = field(default_factory=list)   # [(x,y,z), ...]
    edges: list = field(default_factory=list)      # [(i,j), ...]
    faces: list = field(default_factory=list)      # [[i,j,k,...], ...]
    shape: str = "CUSTOM"
    # Optional exact OpenCascade BREP, base64 encoded.  Mesh fields remain as a
    # display/cache representation, while STEP/boolean operations can use this exact solid.
    brep_b64: str = ""
    KIND = "3DSOLID"
    NAME = "3D 實體"

    def _prims_(self):
        # 2D 幾何核心仍需要平面 primitive（Top 視圖選取、範圍計算、舊工具相容）。
        out = []
        n = len(self.vertices)
        for a, b in self.edges:
            if 0 <= a < n and 0 <= b < n:
                p, q = self.vertices[a], self.vertices[b]
                out.append(('L', float(p[0]), float(p[1]), float(q[0]), float(q[1])))
        return out

    def _bbox_(self):
        if not self.vertices:
            return None
        xs = [float(v[0]) for v in self.vertices]
        ys = [float(v[1]) for v in self.vertices]
        return (min(xs), min(ys), max(xs), max(ys))

    def bbox3d(self):
        if not self.vertices:
            return None
        xs = [float(v[0]) for v in self.vertices]
        ys = [float(v[1]) for v in self.vertices]
        zs = [float(v[2]) for v in self.vertices]
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    def transformed(self, m):
        # 2D MOVE/ROTATE act in XY.  A uniform SCALE must also scale Z so a 3D solid
        # does not become 20x20x10 after a 2x scale.  Exact BREP is invalidated by the
        # generic affine fallback; dedicated 3D commands rebuild/preserve it.
        sc, _rot, mirrored, uniform = G.m_info(m)
        zscale = sc if uniform and not mirrored else 1.0
        vs=[]
        for x,y,z in self.vertices:
            q=G.m_apply(m,(x,y));vs.append((q[0],q[1],z*zscale))
        return self.clone(vertices=vs, brep_b64="")

    def display_mesh(self, max_faces=50000):
        """Return a safe, bounded mesh for interactive display only.

        The authoritative geometry remains ``vertices/faces`` (and ``brep_b64`` when
        available).  Imported STL/STEP meshes may be extremely dense.  v0.6.5.2 used
        position-only vertex clustering for LOD, which could merge the two sides of a
        thin wall and create the apparent spikes/crossing triangles seen in some STL
        files.  v0.6.5.3 first tries topology-aware quadric simplification when the
        optional backend is available, then falls back to *normal-aware* clustering so
        opposite/creased surfaces are never welded just because they occupy a nearby
        spatial cell.
        """
        import math as _math
        limit=max(2000,int(max_faces))
        key=(len(self.vertices),len(self.faces),limit)
        cache=self.__dict__.get("_display_mesh_cache")
        if not isinstance(cache,dict):
            cache={}
            self.__dict__["_display_mesh_cache"]=cache
        if key in cache:
            return cache[key]

        verts=[]; remap={}
        for i,v in enumerate(self.vertices):
            try:x,y,z=(float(v[0]),float(v[1]),float(v[2]))
            except (TypeError,ValueError,IndexError):continue
            if not (_math.isfinite(x) and _math.isfinite(y) and _math.isfinite(z)):continue
            if max(abs(x),abs(y),abs(z))>1e12:continue
            remap[i]=len(verts);verts.append((x,y,z))

        tris=[];seen=set()
        for face in self.faces:
            try:ids=[remap[int(i)] for i in face if int(i) in remap]
            except Exception:continue
            if len(ids)<3:continue
            a=ids[0]
            for k in range(1,len(ids)-1):
                t=(a,ids[k],ids[k+1])
                if len(set(t))<3:continue
                va,vb,vc=(verts[j] for j in t)
                ux,uy,uz=vb[0]-va[0],vb[1]-va[1],vb[2]-va[2]
                vx,vy,vz=vc[0]-va[0],vc[1]-va[1],vc[2]-va[2]
                nx,ny,nz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx
                if nx*nx+ny*ny+nz*nz<1e-24:continue
                sk=tuple(sorted(t))
                if sk in seen:continue
                seen.add(sk);tris.append(t)

        def make_edges(ff,cap=10000):
            es=set()
            for a,b,c in ff:
                es.add((a,b) if a<b else (b,a));es.add((b,c) if b<c else (c,b));es.add((c,a) if c<a else (a,c))
                if len(es)>cap*3:break
            arr=list(es)
            if len(arr)>cap:
                step=max(1,len(arr)//cap);arr=arr[::step][:cap]
            return arr

        if len(tris)<=limit or len(verts)<16:
            data=(verts,tris,make_edges(tris));cache[key]=data;return data

        # Prefer a true topology-preserving simplifier when trimesh's optional
        # fast-simplification backend is installed.  Failure is harmless.
        try:
            import trimesh as _tm
            m=_tm.Trimesh(vertices=verts,faces=tris,process=False,validate=False)
            sm=m.simplify_quadric_decimation(face_count=limit,aggression=5)
            if sm is not None and len(sm.faces)>=4 and len(sm.faces)<=max(limit*2,limit+2000):
                nv=[tuple(map(float,v[:3])) for v in sm.vertices]
                nf=[tuple(map(int,f[:3])) for f in sm.faces]
                data=(nv,nf,make_edges(nf));cache[key]=data;return data
        except Exception:
            pass

        # Area-weighted vertex normals.  Including a quantised normal in each spatial
        # cluster key prevents the inner and outer skins of thin STL walls from welding.
        ns=[[0.0,0.0,0.0] for _ in verts]
        for a,b,c in tris:
            va,vb,vc=verts[a],verts[b],verts[c]
            ux,uy,uz=vb[0]-va[0],vb[1]-va[1],vb[2]-va[2]
            vx,vy,vz=vc[0]-va[0],vc[1]-va[1],vc[2]-va[2]
            nx,ny,nz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx
            for j in (a,b,c):
                ns[j][0]+=nx;ns[j][1]+=ny;ns[j][2]+=nz
        qnorm=[]
        for nx,ny,nz in ns:
            L=(nx*nx+ny*ny+nz*nz)**0.5
            if L<1e-15:qnorm.append((0,0,0))
            else:
                nx,ny,nz=nx/L,ny/L,nz/L
                qnorm.append((int(round(nx*3)),int(round(ny*3)),int(round(nz*3))))

        xs=[v[0] for v in verts];ys=[v[1] for v in verts];zs=[v[2] for v in verts]
        mins=(min(xs),min(ys),min(zs));spans=(max(xs)-mins[0],max(ys)-mins[1],max(zs)-mins[2]);maxspan=max(spans)
        if maxspan<=1e-15:
            data=(verts,tris[:limit],make_edges(tris[:limit]));cache[key]=data;return data

        divisions=max(14,min(260,int((_math.sqrt(limit/5.0))*1.45)))
        best=None
        for _ in range(10):
            cell=maxspan/max(divisions,1)
            sums={};counts={};old_to_key=[]
            for idx,(x,y,z) in enumerate(verts):
                nn=qnorm[idx]
                k=(int((x-mins[0])/cell),int((y-mins[1])/cell),int((z-mins[2])/cell),nn[0],nn[1],nn[2])
                old_to_key.append(k)
                sx,sy,sz=sums.get(k,(0.0,0.0,0.0));sums[k]=(sx+x,sy+y,sz+z);counts[k]=counts.get(k,0)+1
            key_to_new={};nv=[]
            for k,(sx,sy,sz) in sums.items():
                c=counts[k];key_to_new[k]=len(nv);nv.append((sx/c,sy/c,sz/c))
            nf=[];nseen=set()
            for a,b,c in tris:
                t=(key_to_new[old_to_key[a]],key_to_new[old_to_key[b]],key_to_new[old_to_key[c]])
                if len(set(t))<3:continue
                sk=tuple(sorted(t))
                if sk in nseen:continue
                va,vb,vc=(nv[j] for j in t)
                ux,uy,uz=vb[0]-va[0],vb[1]-va[1],vb[2]-va[2];vx,vy,vz=vc[0]-va[0],vc[1]-va[1],vc[2]-va[2]
                cx,cy,cz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx
                if cx*cx+cy*cy+cz*cz<1e-24:continue
                nseen.add(sk);nf.append(t)
            cand=(nv,nf,make_edges(nf))
            if best is None or len(nf)<len(best[1]):best=cand
            if 4<=len(nf)<=limit:best=cand;break
            divisions=max(5,int(divisions*0.72))
        data=best if best and best[1] else (verts,tris[:limit],make_edges(tris[:limit]))
        cache[key]=data
        # Keep several LODs (normal display / highlight / interactive) without
        # allowing imported-model caches to grow without bound.
        if len(cache)>6:
            for k0 in list(cache)[:-6]:cache.pop(k0,None)
        return data

    def hit_arrays(self):
        """Cached NumPy buffers for 3D picking/DUCS hot paths.

        Geometry lists are immutable in normal editing (transforms create clones), so
        rebuilding vertex/edge/triangle arrays on every mouse move is wasted work.
        """
        try:
            import numpy as np
        except Exception:
            return None
        key=(id(self.vertices),id(self.edges),id(self.faces),len(self.vertices),len(self.edges),len(self.faces))
        cached=self.__dict__.get("_hit_numpy_cache")
        if cached and cached[0]==key:return cached[1]
        vv=np.asarray(self.vertices,dtype=float) if self.vertices else np.empty((0,3),dtype=float)
        ee=np.asarray(self.edges,dtype=np.int64) if self.edges else np.empty((0,2),dtype=np.int64)
        tri=[]
        for f in self.faces:
            # Keep procedural quads/ngons out of this cache so the small-face fallback
            # can return the *original* polygon to DUCS (stable face U/V, not a diagonal
            # from a temporary fan triangulation). Imported STL/STEP meshes are triangles.
            if len(f)==3:
                try:tri.append((int(f[0]),int(f[1]),int(f[2])))
                except Exception:pass
        tt=np.asarray(tri,dtype=np.int64) if tri else np.empty((0,3),dtype=np.int64)
        data=(vv,ee,tt)
        self.__dict__["_hit_numpy_cache"]=(key,data)
        return data

    def snaps(self):
        # Legacy 2D OSNAP projection used by the 2D drafting workspace.
        return [("END", float(x), float(y)) for x, y, z in self.vertices]

    def snap_points3d(self, max_points=6000):
        """Return bounded XYZ object-snap candidates for 3D editing.

        Exact STEP/native solids use their OpenCascade topology when available, so a
        circular cylinder rim exposes its *true* centre and a BOX exposes real vertex,
        edge-midpoint and face-centre snaps.  Mesh-only STL objects fall back to the
        feature-edge cache without walking hundreds of thousands of triangles on every
        mouse move.  The result is cached on the entity and is display-only metadata; it
        is rebuilt automatically after clone/transform operations.
        """
        limit=max(128,int(max_points))
        key=(len(self.vertices),len(self.edges),len(self.faces),len(self.brep_b64),limit)
        cached=self.__dict__.get("_snap3d_cache")
        if cached and cached[0]==key:
            return cached[1]

        out=[]; seen=set()
        b3=self.bbox3d()
        span=1.0 if not b3 else max(b3[3]-b3[0],b3[4]-b3[1],b3[5]-b3[2],1.0)
        eps=max(span*1e-8,1e-9)
        def add(kind,p):
            if len(out)>=limit:return
            try:q=(float(p[0]),float(p[1]),float(p[2]))
            except Exception:return
            if not all(math.isfinite(v) for v in q):return
            k=(str(kind),round(q[0]/eps),round(q[1]/eps),round(q[2]/eps))
            if k in seen:return
            seen.add(k);out.append((str(kind),q))

        # Exact CAD topology is the preferred source.  Edge.Center() gives the real
        # centre for circles/ellipses in CadQuery/OCC rather than a tessellation vertex.
        if self.brep_b64:
            try:
                from .io_utils import _shape_from_brep_b64
                sh=_shape_from_brep_b64(self.brep_b64)
                if sh is not None:
                    verts=list(sh.Vertices())
                    if len(verts)>2500:
                        step=max(1,len(verts)//2500);verts=verts[::step][:2500]
                    for v in verts:
                        try:add("END",v.toTuple())
                        except Exception:pass
                    edges=list(sh.Edges())
                    if len(edges)>2500:
                        step=max(1,len(edges)//2500);edges=edges[::step][:2500]
                    for e in edges:
                        try:
                            gt=str(e.geomType()).upper(); c=e.Center().toTuple()
                            add("CEN" if gt in ("CIRCLE","ELLIPSE") else "MID",c)
                        except Exception:pass
                    faces=list(sh.Faces())
                    if len(faces)>1200:
                        step=max(1,len(faces)//1200);faces=faces[::step][:1200]
                    for f in faces:
                        try:add("CEN",f.Center().toTuple())
                        except Exception:pass
            except Exception:
                pass

        # Mesh/native fallback.  Feature edges are intentionally bounded on import.
        if not out:
            n=len(self.vertices); used=set()
            edges=self.edges
            if len(edges)>2500:
                step=max(1,len(edges)//2500);edges=edges[::step][:2500]
            for ia,ib in edges:
                if not (0<=int(ia)<n and 0<=int(ib)<n):continue
                ia,ib=int(ia),int(ib);a=self.vertices[ia];b=self.vertices[ib]
                if ia not in used:add("END",a);used.add(ia)
                if ib not in used:add("END",b);used.add(ib)
                add("MID",((a[0]+b[0])*0.5,(a[1]+b[1])*0.5,(a[2]+b[2])*0.5))
            # Small procedural solids have meaningful polygon faces; expose their centres.
            if len(self.faces)<=512:
                for face in self.faces:
                    ids=[int(i) for i in face if 0<=int(i)<n]
                    if len(ids)<3:continue
                    add("CEN",(sum(self.vertices[i][0] for i in ids)/len(ids),
                               sum(self.vertices[i][1] for i in ids)/len(ids),
                               sum(self.vertices[i][2] for i in ids)/len(ids)))

        # Geometric-centre snap is useful for all solid types, including mesh-only STL.
        if b3:
            gc=((b3[0]+b3[3])*0.5,(b3[1]+b3[4])*0.5,(b3[2]+b3[5])*0.5)
            add("GCE",gc)
            # CEN is enabled by default in PyCAD.  For mesh-only solids also expose the
            # object centre as CEN so MOVE3D remains practical without changing settings.
            if not self.brep_b64:add("CEN",gc)

        self.__dict__["_snap3d_cache"]=(key,out)
        return out

    def grips(self):
        # Solid grip editing is not implemented yet.  Returning projected XY bbox
        # grips is misleading in 3D because those points have no stable Z meaning.
        return []


CLASSES = {c.KIND: c for c in (Line, Circle, Arc, Polyline, Ellipse, Spline, Point, Text, MText, Hatch, XLine,
                               Dim, Insert, Array, Solid3D)}


# ---------------------------------------------------------------- 標註幾何
def _merge_boxes(bs):
    bs = [b for b in bs if b]
    if not bs:
        return None
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def _arrow(tip, direction_deg, size, kw):
    """實心箭頭：tip 為尖端，箭身朝 direction_deg 方向延伸。"""
    b = G.polar(tip, direction_deg, size)
    return Hatch(loops=[[tip, G.polar(b, direction_deg + 90, size / 6.0), G.polar(b, direction_deg - 90, size / 6.0)]],
                 pattern="SOLID", **kw)


def _readable(a):
    a %= 360.0
    return a - 180.0 if 90.0 < a <= 270.0 else a


def _dim_parts(d):
    kw = dict(layer=d.layer, color=d.color, ltype="Continuous", lw=d.lw)
    th, asz = d.th, d.asz
    gap, exo, exe = th * 0.25, th * 0.25, th * 0.5
    p = d.pts
    out = []
    L = lambda a, b: out.append(Line(x1=a[0], y1=a[1], x2=b[0], y2=b[1], **kw))
    label = d.label()
    k = d.kind
    try:
        if k in ("LIN", "ALI") and len(p) >= 3:
            if k == "ALI":
                if G.dist(p[0], p[1]) < G.EPS:
                    return out
                ua = G.ang(p[0], p[1])
            else:
                ua = d.rot
            u = (math.cos(math.radians(ua)), math.sin(math.radians(ua)))
            proj = lambda q: (p[2][0] + u[0] * ((q[0] - p[2][0]) * u[0] + (q[1] - p[2][1]) * u[1]),
                              p[2][1] + u[1] * ((q[0] - p[2][0]) * u[0] + (q[1] - p[2][1]) * u[1]))
            a, b = proj(p[0]), proj(p[1])
            for o, q in ((p[0], a), (p[1], b)):
                dd = G.dist(o, q)
                if dd > exo:
                    ea = G.ang(o, q)
                    L(G.polar(o, ea, exo), G.polar(q, ea, exe))
            val = G.dist(a, b)
            if val > G.EPS:
                da = G.ang(a, b)
                if val >= asz * 3.0:
                    L(a, b)
                    out.append(_arrow(a, da, asz, kw))
                    out.append(_arrow(b, da + 180, asz, kw))
                else:
                    L(G.polar(a, da + 180, asz * 2), G.polar(b, da, asz * 2))
                    out.append(_arrow(a, da + 180, asz, kw))
                    out.append(_arrow(b, da, asz, kw))
            ra = _readable(ua)
            m = G.polar(G.mid(a, b), ra + 90.0, gap)
            out.append(Text(x=m[0], y=m[1], text=label, height=th, rot=ra % 360.0, halign=1, valign=1, **kw))
        elif k in ("RAD", "DIA") and len(p) >= 3:
            c, on, tl = p[0], p[1], p[2]
            r = G.dist(c, on)
            a = G.ang(c, on)
            outside = G.dist(c, tl) > r
            if k == "DIA":
                op = G.polar(c, a + 180, r)
                L(op, on)
                out.append(_arrow(op, a, asz, kw))
                out.append(_arrow(on, a + 180, asz, kw))
                if outside:
                    L(on, tl)
            else:
                if outside:
                    L(on, tl)
                    out.append(_arrow(on, a, asz, kw))
                else:
                    L(c, on)
                    out.append(_arrow(on, a + 180, asz, kw))
            right = tl[0] >= c[0]
            land = (tl[0] + (asz if right else -asz), tl[1])
            if outside:
                L(tl, land)
            tp = (land[0] + (gap if right else -gap), land[1]) if outside else (tl[0], tl[1] + gap)
            out.append(Text(x=tp[0], y=tp[1], text=label, height=th, rot=0.0,
                            halign=(0 if right else 2) if outside else 1, valign=2 if outside else 1, **kw))
        elif k == "ANG" and len(p) >= 4:
            v = p[0]
            r = G.dist(v, p[3])
            a1, a2, al = G.ang(v, p[1]), G.ang(v, p[2]), G.ang(v, p[3])
            if (al - a1) % 360.0 > (a2 - a1) % 360.0:
                a1, a2 = a2, a1
            span = (a2 - a1) % 360.0
            if r > G.EPS and span > 1e-9:
                out.append(Arc(cx=v[0], cy=v[1], r=r, a0=a1, a1=a2, **kw))
                da = math.degrees(asz / r) / 2.0
                out.append(_arrow(G.polar(v, a1, r), a1 + 90 + da, asz, kw))
                out.append(_arrow(G.polar(v, a2, r), a2 - 90 - da, asz, kw))
                for q, aa in ((p[1], a1), (p[2], a2)):
                    if r > G.dist(v, q) + exo:
                        L(G.polar(q, aa, exo), G.polar(v, aa, r + exe))
                am = a1 + span / 2.0
                ra = _readable(am - 90.0)
                tp = G.polar(v, am, r + gap + (th if abs((ra - (am - 90.0)) % 360.0) > 1 else 0.0))
                out.append(Text(x=tp[0], y=tp[1], text=label, height=th, rot=ra % 360.0, halign=1, valign=1, **kw))
        elif k == "LDR" and len(p) >= 2:
            for i in range(len(p) - 1):
                L(p[i], p[i + 1])
            if G.dist(p[0], p[1]) > G.EPS:
                out.append(_arrow(p[0], G.ang(p[0], p[1]), asz, kw))
            right = p[-1][0] >= p[-2][0]
            land = (p[-1][0] + (asz if right else -asz), p[-1][1])
            L(p[-1], land)
            if label:
                out.append(MText(x=land[0] + (gap if right else -gap), y=land[1], text=label, height=th,
                                 attach=4 if right else 6, **kw))
    except (ZeroDivisionError, ValueError):
        pass
    return out


# ---------------------------------------------------------------- 文件
DEFAULT_VARS = {
    "LTSCALE": 1.0, "DIMSCALE": 1.0, "TEXTSIZE": 2.5, "DIMTXT": 2.5, "DIMASZ": 2.5, "DIMDEC": 2,
    "CECOLOR": BYLAYER, "CELTYPE": "ByLayer", "CELWEIGHT": LW_BYLAYER,
    "FILLETRAD": 0.0, "CHAMFERA": 0.0, "CHAMFERB": 0.0, "OFFSETDIST": 1.0, "POLYSIDES": 4,
    "HPNAME": "ANSI31", "HPSCALE": 1.0, "HPANG": 0.0, "LUPREC": 4, "MIRRKEEP": 1, "INSUNITS": 4,
}


class Document:
    def __init__(self):
        self.entities = []
        self.layers = {"0": Layer("0")}
        self.current_layer = "0"
        self.blocks = {}
        self.block_rev = 0
        self.linetypes = {k: list(v) for k, v in LINETYPES.items()}
        self.vars = dict(DEFAULT_VARS)
        self.undo_stack = []
        self.redo_stack = []
        self.modified = False
        self.path = None
        self.source = "PYCAD"
        self.name = "Drawing1.pycad"

    # ---- 復原
    def _state(self):
        return (list(self.entities), {k: replace(v) for k, v in self.layers.items()}, dict(self.blocks),
                self.current_layer, dict(self.vars))

    def _restore(self, st):
        self.entities, self.layers, self.blocks, self.current_layer, self.vars = \
            list(st[0]), {k: replace(v) for k, v in st[1].items()}, dict(st[2]), st[3], dict(st[4])
        self.block_rev += 1

    def push_undo(self):
        self.undo_stack.append(self._state())
        if len(self.undo_stack) > 200:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.modified = True

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(self._state())
        self._restore(self.undo_stack.pop())
        self.modified = True
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(self._state())
        self._restore(self.redo_stack.pop())
        self.modified = True
        return True

    # ---- stable entity identity / associations
    def ensure_unique_uids(self):
        """Repair missing/duplicate entity ids without changing geometry.

        Old .pycad files had no uid.  Copy-like operations can also preserve a clone's
        uid until it is inserted; this routine makes document-level identities unique.
        """
        seen=set(); out=[]
        for e in self.entities:
            u=str(getattr(e,"uid","") or "")
            if not u or u in seen:
                e=e.clone(uid=uuid.uuid4().hex)
                u=e.uid
            seen.add(u); out.append(e)
        self.entities=out

    def by_uid(self, uid):
        return next((e for e in self.entities if getattr(e,"uid",None)==uid),None)

    def refresh_associative_hatches(self, changed_uids=None):
        """Regenerate associative HATCH boundaries from their source entities.

        Returns True when one or more hatch objects were replaced.  If a source was
        erased, the hatch keeps its last valid geometry but drops that association
        rather than disappearing or jumping to unrelated geometry.
        """
        changed=set(changed_uids or ())
        replaced=False; out=[]
        # Local import avoids a model -> edit_ops import cycle at module load time.
        from . import edit_ops as _E
        for e in self.entities:
            if not isinstance(e,Hatch) or not e.boundary_uids:
                out.append(e); continue
            flat={u for grp in e.boundary_uids for u in (grp if isinstance(grp,(list,tuple)) else [grp])}
            if changed and not (flat & changed):
                out.append(e); continue
            loops=[]; prim_loops=[]; groups=[]
            valid=True
            for grp in e.boundary_uids:
                ids=list(grp) if isinstance(grp,(list,tuple)) else [grp]
                src=[self.by_uid(u) for u in ids]
                src=[x for x in src if x is not None and not isinstance(x,Hatch)]
                if not src:
                    valid=False; break
                # A selected closed entity maps exactly.  Multi-entity loops are
                # reconstructed only when their primitive chain closes cleanly.
                if len(src)==1:
                    lp=_E.closed_outline(src[0])
                    if not lp:
                        valid=False; break
                    loops.append(lp); prim_loops.append([tuple(pr) for pr in src[0].prims()]); groups.append(ids)
                else:
                    ps=[]
                    for x in src: ps.extend(x.prims())
                    pts=G.flatten_prims(ps,5.0)
                    if len(pts)<4 or G.dist(pts[0],pts[-1])>1e-5:
                        valid=False; break
                    loops.append(pts[:-1]); prim_loops.append([tuple(pr) for pr in ps]); groups.append(ids)
            if valid and loops:
                ne=e.clone(loops=loops,loop_prims=prim_loops,boundary_uids=groups)
                out.append(ne); replaced |= (ne.loops!=e.loops or ne.loop_prims!=e.loop_prims)
            else:
                # Keep the visible hatch but detach missing/invalid references.
                out.append(e.clone(boundary_uids=[])); replaced=True
        if replaced:self.entities=out
        return replaced

    # ---- 圖層與性質解析
    def layer(self, name):
        ly = self.layers.get(name)
        if ly is None:
            ly = Layer(name)
            self.layers[name] = ly
        return ly

    def color_of(self, e):
        c = e.color
        if c == BYLAYER:
            c = self.layer(e.layer).color
        elif c == BYBLOCK:
            c = 7
        return c

    def rgb_of(self, e):
        """Return explicit DXF true-color when present, otherwise None."""
        tc = int(getattr(e, "truecolor", -1) or -1)
        if 0 <= tc <= 0xFFFFFF:
            return ((tc >> 16) & 255, (tc >> 8) & 255, tc & 255)
        return None

    def ltype_of(self, e):
        lt = e.ltype
        if lt in ("ByLayer", "BYLAYER", ""):
            lt = self.layer(e.layer).ltype
        elif lt in ("ByBlock", "BYBLOCK"):
            lt = "Continuous"
        return lt

    def lw_of(self, e):
        lw = e.lw
        if lw == LW_BYLAYER:
            lw = self.layer(e.layer).lw
        if lw in (LW_DEFAULT, LW_BYBLOCK):
            lw = 25
        return lw

    def pattern(self, name):
        """線型樣式（mm）；支援 DASHED2 / DASHEDX2 這類縮放變體。"""
        pat = self.linetypes.get(name)
        if pat is None:
            up = name.upper()
            for k, v in self.linetypes.items():
                if k.upper() == up:
                    return v
            if up.endswith("X2") and up[:-2] in LINETYPES:
                pat = [x * 2 for x in LINETYPES[up[:-2]]]
            elif up.endswith("2") and up[:-1] in LINETYPES:
                pat = [x * 0.5 for x in LINETYPES[up[:-1]]]
            else:
                pat = []
            self.linetypes[name] = pat
        return pat

    def visible(self, e):
        ly = self.layer(e.layer)
        return ly.on and not ly.frozen

    def editable(self, e):
        ly = self.layer(e.layer)
        return ly.on and not ly.frozen and not ly.locked

    def new_props(self):
        return dict(layer=self.current_layer, color=self.vars["CECOLOR"], ltype=self.vars["CELTYPE"],
                    lw=self.vars["CELWEIGHT"])

    # ---- 複合圖元展開
    def expand(self, e, depth=0):
        """把標註、圖塊參考展開成可直接繪製的葉節點圖元。"""
        if isinstance(e, Array):
            out = []
            for part in e.parts():
                out.extend(self.expand(part, depth + 1))
            return out
        if isinstance(e, Dim):
            return e.parts()
        if isinstance(e, Insert):
            c = e.__dict__.get("_exp")
            if c is not None and c[0] == self.block_rev:
                return c[1]
            out = []
            blk = self.blocks.get(e.name)
            if blk is not None and depth < 8:
                m = e.matrix(blk)
                for be in blk.entities:
                    for leaf in self.expand(be, depth + 1):
                        t = leaf.transformed(m)
                        ch = {}
                        if t.layer == "0":
                            ch["layer"] = e.layer
                        if t.color == BYBLOCK:
                            ch["color"] = e.color
                        if t.ltype in ("ByBlock", "BYBLOCK"):
                            ch["ltype"] = e.ltype
                        out.append(t.clone(**ch) if ch else t)
            e.__dict__["_exp"] = (self.block_rev, out)
            return out
        return [e]

    def bbox(self, e):
        if isinstance(e, (Insert,Array)):
            return _merge_boxes([x.bbox() for x in self.expand(e)])
        return e.bbox()

    def prims(self, e):
        if isinstance(e, (Insert,Array)):
            return [p for x in self.expand(e) for p in x.prims()]
        return e.prims()

    def snaps(self, e):
        if isinstance(e, (Insert,Array)):
            out = list(e.snaps()) if not isinstance(e,Array) or e.bbox() else []
            for x in self.expand(e):out += x.snaps()
            return out
        return e.snaps()

    def hit_dist(self, e, p):
        """點到圖元的距離（文字與實心填充在範圍內視為 0）。

        Large associative arrays are hit-tested parametrically instead of expanding
        every member on every mouse move.  This keeps 40x40+ arrays interactive.
        """
        if isinstance(e, Array):
            total=(max(1,int(e.count)) if e.mode.upper()=="POLAR" else max(1,int(e.rows))*max(1,int(e.cols)))
            if total > 256 and e.source:
                candidates=[]
                if e.mode.upper()=="POLAR":
                    n=max(1,int(e.count)); step=e.fill/n if abs(abs(e.fill)-360.0)<1e-9 else e.fill/max(1,n-1)
                    sb=_merge_boxes([x.bbox() for x in e.source]); o=((sb[0]+sb[2])/2,(sb[1]+sb[3])/2) if sb else (e.cx,e.cy)
                    a0=G.ang((e.cx,e.cy),o); ap=G.ang((e.cx,e.cy),p)
                    if abs(step)>G.EPS:
                        k0=int(round(((ap-a0+540.0)%360.0-180.0)/step))
                    else:k0=0
                    for dk in range(-2,3):
                        k=k0+dk
                        if 0<=k<n:candidates.append(k)
                    candidates += [0,n-1]
                    seen=set();best=float("inf")
                    for k in candidates:
                        if k in seen:continue
                        seen.add(k)
                        if e.rotate_items:
                            m=G.m_rotate((e.cx,e.cy),step*k)
                        else:
                            t=G.m_apply(G.m_rotate((e.cx,e.cy),step*k),o);m=G.m_translate(t[0]-o[0],t[1]-o[1])
                        for src in e.source:
                            best=min(best,self.hit_dist(src.transformed(m),p))
                    return best
                cv=e.col_vec if any(abs(float(v))>G.EPS for v in e.col_vec) else (float(e.dx),0.0)
                rv=e.row_vec if any(abs(float(v))>G.EPS for v in e.row_vec) else (0.0,float(e.dy))
                sb=_merge_boxes([x.bbox() for x in e.source]); o=((sb[0]+sb[2])/2,(sb[1]+sb[3])/2) if sb else (0.0,0.0)
                vx,vy=p[0]-o[0],p[1]-o[1];det=cv[0]*rv[1]-cv[1]*rv[0]
                if abs(det)>G.EPS:
                    jf=(vx*rv[1]-vy*rv[0])/det; iff=(cv[0]*vy-cv[1]*vx)/det
                    js=range(max(0,int(round(jf))-1),min(max(1,int(e.cols)),int(round(jf))+2))
                    ins=range(max(0,int(round(iff))-1),min(max(1,int(e.rows)),int(round(iff))+2))
                    best=float("inf")
                    for i in ins:
                        for j in js:
                            m=G.m_translate(j*cv[0]+i*rv[0],j*cv[1]+i*rv[1])
                            for src in e.source:best=min(best,self.hit_dist(src.transformed(m),p))
                    return best
        best = float("inf")
        for x in self.expand(e):
            if isinstance(x, (Text, MText)):
                if G.point_in_poly(p, x.corners()):
                    return 0.0
                continue
            if isinstance(x, Point):
                best = min(best, G.dist(p, (x.x, x.y)))
                continue
            if isinstance(x, Hatch) and x.contains(p):
                return 0.0
            for pr in x.prims():
                d = G.nearest_on_prim(p, pr)[0]
                if d < best:
                    best = d
        return best

    def extents(self, ents=None):
        return _merge_boxes([self.bbox(e) for e in (self.entities if ents is None else ents)
                             if ents is not None or self.visible(e)])

    # ---- 序列化
    def to_json(self):
        return {
            "format": "PyCAD2D", "version": 6,
            "vars": self.vars, "current_layer": self.current_layer,
            "layers": [vars(l) for l in self.layers.values()],
            "linetypes": self.linetypes,
            "blocks": [{"name": b.name, "bx": b.bx, "by": b.by, "entities": [e.to_dict() for e in b.entities]}
                       for b in self.blocks.values()],
            "entities": [e.to_dict() for e in self.entities],
        }

    @classmethod
    def from_json(cls, d):
        doc = cls()
        if int(d.get("version", 4)) < 5:
            doc.entities = [e for e in (_legacy(x) for x in d.get("entities", [])) if e is not None]
            for e in doc.entities:
                doc.layer(e.layer)
            return doc
        doc.vars.update(d.get("vars", {}))
        doc.layers = {}
        for l in d.get("layers", []):
            doc.layers[l["name"]] = Layer(**l)
        doc.layers.setdefault("0", Layer("0"))
        doc.current_layer = d.get("current_layer", "0") if d.get("current_layer", "0") in doc.layers else "0"
        for k, v in d.get("linetypes", {}).items():
            doc.linetypes[k] = list(v)
        for b in d.get("blocks", []):
            doc.blocks[b["name"]] = Block(b["name"], b.get("bx", 0.0), b.get("by", 0.0),
                                          [e for e in (entity_from_dict(x) for x in b.get("entities", [])) if e])
        doc.entities = [e for e in (entity_from_dict(x) for x in d.get("entities", [])) if e is not None]
        doc.ensure_unique_uids()
        for e in doc.entities:
            doc.layer(e.layer)
        return doc


def _tup(v):
    return [tuple(x) for x in v]


def entity_from_dict(d):
    cls = CLASSES.get(d.get("type"))
    if cls is None:
        return None
    names = {f.name for f in fields(cls)}
    kw = {k: v for k, v in d.items() if k in names}
    for k in ("pts", "fit", "ctrl", "vertices", "edges", "widths"):
        if k in kw:
            kw[k] = _tup(kw[k])
    if "loops" in kw:
        kw["loops"] = [_tup(lp) for lp in kw["loops"]]
    if cls is Array and "source" in kw:
        kw["source"] = [e for e in (entity_from_dict(x) for x in kw["source"]) if e is not None]
    return cls(**kw)


def _legacy(d):
    """讀取 v0.4 以前的 .pycad 物件。"""
    t = d.get("type")
    ly = d.get("layer", "0")
    if t == "LineEntity":
        return Line(layer=ly, x1=d["x1"], y1=d["y1"], x2=d["x2"], y2=d["y2"])
    if t == "CircleEntity":
        return Circle(layer=ly, cx=d["cx"], cy=d["cy"], r=d["radius"])
    if t == "RectEntity":
        return Polyline(layer=ly, closed=True, pts=[(d["x1"], d["y1"], 0.0), (d["x2"], d["y1"], 0.0),
                                                    (d["x2"], d["y2"], 0.0), (d["x1"], d["y2"], 0.0)])
    if t == "PolylineEntity":
        return Polyline(layer=ly, pts=[(p[0], p[1], 0.0) for p in d.get("points", [])])
    if t == "ArcEntity":
        a0, sp = d.get("start_angle", 0.0), d.get("span_angle", 90.0)
        if sp < 0:
            a0, sp = a0 + sp, -sp
        return Arc(layer=ly, cx=d["cx"], cy=d["cy"], r=d["radius"], a0=a0 % 360.0, a1=(a0 + sp) % 360.0)
    if t == "TextEntity":
        return Text(layer=ly, x=d["x"], y=d["y"], text=d.get("text", ""), height=d.get("height", 12.0))
    if t == "LinearDimEntity":
        horiz = abs(d["x2"] - d["x1"]) >= abs(d["y2"] - d["y1"])
        return Dim(layer=ly, kind="LIN", rot=0.0 if horiz else 90.0, th=8.0, asz=8.0,
                   pts=[(d["x1"], d["y1"]), (d["x2"], d["y2"]), (d["lx"], d["ly"])])
    return None
