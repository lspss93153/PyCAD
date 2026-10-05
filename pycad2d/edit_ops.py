# SPDX-License-Identifier: GPL-3.0-only
"""修改類指令用到的幾何運算：路徑切割、修剪、延伸、偏移、圓角、倒角、拉伸、接合、邊界偵測。"""
import math
from . import geometry as G
from .model import (Line, Circle, Arc, Polyline, Ellipse, Spline, Point, Text, MText, Hatch, XLine, Dim, Insert, Array, Solid3D)

TOL = 1e-6


# ---------------------------------------------------------------- 路徑（有方向的 prim 串）
def path_of(e):
    """回傳 (prims, closed)；不支援的圖元回傳 (None, False)。"""
    if isinstance(e, (Line, Arc, XLine)):
        return list(e.prims()), False
    if isinstance(e, Circle):
        return list(e.prims()), True
    if isinstance(e, Polyline):
        return list(e.prims()), e.closed
    if isinstance(e, Ellipse):
        return list(e.prims()), e.full()
    if isinstance(e, Spline):
        ps=list(e.prims())
        closed=bool(e.closed or (ps and G.dist(G.prim_start(ps[0]),G.prim_end(ps[-1]))<TOL))
        return ps,closed
    return None, False


def path_len(prims):
    return sum(G.prim_len(p) for p in prims)


def path_station(prims, p):
    """點 p 在路徑上最接近位置的里程。"""
    best, acc, out = float("inf"), 0.0, 0.0
    for pr in prims:
        d, q = G.nearest_on_prim(p, pr)
        if d < best:
            best, out = d, acc + G.prim_station(pr, q)
        acc += G.prim_len(pr)
    return out


def path_point(prims, s):
    acc = 0.0
    for pr in prims:
        L = G.prim_len(pr)
        if s <= acc + L + 1e-12:
            return G.prim_point(pr, max(0.0, s - acc))
        acc += L
    return G.prim_end(prims[-1])


def path_tangent(prims, s):
    acc = 0.0
    for pr in prims:
        L = G.prim_len(pr)
        if s <= acc + L + 1e-12:
            return G.prim_tangent(pr, max(0.0, s - acc))
        acc += L
    return G.prim_tangent(prims[-1], G.prim_len(prims[-1]))


def sub_path(prims, s0, s1):
    out, acc = [], 0.0
    for pr in prims:
        L = G.prim_len(pr)
        a, b = max(s0, acc), min(s1, acc + L)
        if b - a > 1e-9:
            sp = G.sub_prim(pr, a - acc, b - acc)
            if sp:
                out.append(sp)
        acc += L
    return out


def reverse_prims(prims):
    out = []
    for pr in reversed(prims):
        if pr[0] == 'L':
            out.append(('L', pr[3], pr[4], pr[1], pr[2]))
        else:
            out.append(pr[:6] + (not (len(pr) < 7 or pr[6]),))
    return out


def _ellipse_param(e,p):
    ux,uy=float(e.mx),float(e.my);vx,vy=-float(e.my)*float(e.ratio),float(e.mx)*float(e.ratio)
    dx,dy=float(p[0])-float(e.cx),float(p[1])-float(e.cy);det=ux*vy-uy*vx
    if abs(det)<1e-15:return 0.0
    co=(dx*vy-dy*vx)/det;si=(ux*dy-uy*dx)/det
    return math.atan2(si,co)%G.TWO_PI if hasattr(G,"TWO_PI") else math.atan2(si,co)%(2*math.pi)


def rebuild(e, prims, closed=False):
    """把 prim 串變回圖元（盡量維持原本的類型）。"""
    if not prims:
        return None
    kw = e.common()
    if len(prims) == 1 and not closed:
        pr = prims[0]
        if pr[0] == 'L' and not isinstance(e, Polyline):
            return Line(x1=pr[1], y1=pr[2], x2=pr[3], y2=pr[4], **kw)
        if pr[0] == 'A' and not isinstance(e, Polyline):
            return Arc(cx=pr[1], cy=pr[2], r=pr[3], a0=pr[4] % 360.0, a1=(pr[4] + pr[5]) % 360.0, **kw)
    if isinstance(e,Ellipse):
        a=G.prim_start(prims[0]);b=G.prim_end(prims[-1])
        if closed:return e.clone()
        return e.clone(t0=_ellipse_param(e,a),t1=_ellipse_param(e,b))
    pts = G.prims_to_poly(prims)
    if closed and len(pts) > 1:pts=pts[:-1]
    if isinstance(e,Spline):
        xy=[(float(q[0]),float(q[1])) for q in pts]
        return Spline(fit=xy,ctrl=[],knots=[],degree=min(3,max(1,len(xy)-1)),closed=closed,**kw)
    return Polyline(pts=pts, closed=closed, **kw)


def _stations_on(prims, cutters):
    sts, acc = [], 0.0
    for pr in prims:
        for q in cutters:
            for ip in G.intersect(pr, q):
                sts.append(acc + G.prim_station(pr, ip))
        acc += G.prim_len(pr)
    return sts


def _xline_piece(e, prims):
    """建構線被切過之後：碰到無限遠端的那段變成射線。"""
    pr = prims[0]
    a, b = (pr[1], pr[2]), (pr[3], pr[4])
    far = e.FAR * 0.5
    da, db = G.dist(a, (e.x, e.y)), G.dist(b, (e.x, e.y))
    kw = e.common()
    if da > far and db > far:
        return e
    if da > far:
        return XLine(x=b[0], y=b[1], dx=a[0] - b[0], dy=a[1] - b[1], ray=True, **kw)
    if db > far:
        return XLine(x=a[0], y=a[1], dx=b[0] - a[0], dy=b[1] - a[1], ray=True, **kw)
    return Line(x1=a[0], y1=a[1], x2=b[0], y2=b[1], **kw)


def cut_out(e, lo, hi):
    """移除圖元上 [lo, hi] 這段里程，回傳剩下的圖元清單。"""
    prims, closed = path_of(e)
    total = path_len(prims)
    mk = (lambda ps: _xline_piece(e, ps)) if isinstance(e, XLine) else (lambda ps: rebuild(e, ps))
    if closed:
        a, b = hi % total, lo % total
        if isinstance(e, Circle):
            pa, pb = path_point(prims, a), path_point(prims, b)
            c = (e.cx, e.cy)
            return [Arc(cx=e.cx, cy=e.cy, r=e.r, a0=G.ang(c, pa), a1=G.ang(c, pb), **e.common())]
        ps = sub_path(prims, a, b) if a < b else sub_path(prims, a, total) + sub_path(prims, 0.0, b)
        r = rebuild(e, ps)
        return [r] if r else []
    out = []
    if lo is not None and lo > TOL:
        out.append(mk(sub_path(prims, 0.0, lo)))
    if hi is not None and hi < total - TOL:
        out.append(mk(sub_path(prims, hi, total)))
    return [x for x in out if x is not None]


def trim_entity(doc, e, pick, edges):
    """修剪：回傳取代 e 的圖元清單；無法修剪時回傳 None。"""
    prims, closed = path_of(e)
    if not prims:
        return None
    cutters = [p for ed in edges if ed is not e for p in doc.prims(ed)]
    sts = sorted(_stations_on(prims, cutters))
    if not sts:
        return None
    total = path_len(prims)
    tol = max(TOL, total * 1e-9)
    sp = path_station(prims, pick)
    lo = max([s for s in sts if s < sp - tol], default=None)
    hi = min([s for s in sts if s > sp + tol], default=None)
    if closed:
        uniq = [s for i, s in enumerate(sts) if i == 0 or s - sts[i - 1] > tol]
        if len(uniq) < 2:
            return None
        if lo is None:
            lo = uniq[-1] - total
        if hi is None:
            hi = uniq[0] + total
        return cut_out(e, lo, hi)
    if lo is None and hi is None:
        return None
    return cut_out(e, lo, hi)


def extend_entity(doc, e, pick, edges):
    """延伸：回傳新的圖元；找不到邊界時回傳 None。"""
    bounds = [p for ed in edges if ed is not e for p in doc.prims(ed)]
    if isinstance(e, Line):
        a, b = (e.x1, e.y1), (e.x2, e.y2)
        at_start = G.dist(pick, a) < G.dist(pick, b)
        end, other = (a, b) if at_start else (b, a)
        q = _extend_ray(other, end, bounds)
        if q is None:
            return None
        return e.clone(x1=q[0], y1=q[1]) if at_start else e.clone(x2=q[0], y2=q[1])
    if isinstance(e, Arc):
        s, t = e.ends()
        c = (e.cx, e.cy)
        at_start = G.dist(pick, s) < G.dist(pick, t)
        circ = ('A', e.cx, e.cy, e.r, 0.0, 360.0)
        best = None
        for b in bounds:
            for ip in G.intersect(circ, b):
                a = G.ang(c, ip)
                if G.on_arc(a, e.a0 % 360.0, e.span()):
                    continue
                d = (e.a0 - a) % 360.0 if at_start else (a - e.a1) % 360.0
                if best is None or d < best[0]:
                    best = (d, a)
        if best is None:
            return None
        return e.clone(a0=best[1]) if at_start else e.clone(a1=best[1])
    if isinstance(e, Polyline) and not e.closed and len(e.pts) >= 2:
        pts = list(e.pts)
        at_start = G.dist(pick, pts[0]) < G.dist(pick, pts[-1])
        if at_start:
            if abs(pts[0][2]) > 1e-12:
                return None
            q = _extend_ray(pts[1], pts[0], bounds)
            if q is None:
                return None
            pts[0] = (q[0], q[1], pts[0][2])
        else:
            if abs(pts[-2][2]) > 1e-12:
                return None
            q = _extend_ray(pts[-2], pts[-1], bounds)
            if q is None:
                return None
            pts[-1] = (q[0], q[1], pts[-1][2])
        return e.clone(pts=pts)
    return None


def _extend_ray(other, end, bounds):
    seg = ('L', other[0], other[1], end[0], end[1])
    dx, dy = end[0] - other[0], end[1] - other[1]
    best = None
    for b in bounds:
        for ip in G.intersect(seg, b, True, False):
            t = (ip[0] - end[0]) * dx + (ip[1] - end[1]) * dy
            if t > 1e-9 and (best is None or t < best[0]):
                best = (t, ip)
    return best[1] if best else None


# ---------------------------------------------------------------- 偏移
def offset_entity(e, d, side):
    """往 side 點那一側偏移 d。"""
    if isinstance(e, Line):
        dx, dy = e.x2 - e.x1, e.y2 - e.y1
        L = math.hypot(dx, dy)
        if L < G.EPS:
            return None
        s = 1.0 if G.cross(dx, dy, side[0] - e.x1, side[1] - e.y1) >= 0 else -1.0
        nx, ny = -dy / L * d * s, dx / L * d * s
        return e.clone(x1=e.x1 + nx, y1=e.y1 + ny, x2=e.x2 + nx, y2=e.y2 + ny)
    if isinstance(e, XLine):
        L = math.hypot(e.dx, e.dy)
        s = 1.0 if G.cross(e.dx, e.dy, side[0] - e.x, side[1] - e.y) >= 0 else -1.0
        return e.clone(x=e.x - e.dy / L * d * s, y=e.y + e.dx / L * d * s)
    if isinstance(e, (Circle, Arc)):
        r = e.r + d if G.dist((e.cx, e.cy), side) >= e.r else e.r - d
        return e.clone(r=r) if r > G.EPS else None
    if isinstance(e, Polyline):
        prims = e.prims()
        if not prims:
            return None
        # Closed straight-sided profiles use a topology-aware polygon offset.  This
        # rejects over-large inward offsets and cleans concave self-intersections.
        if e.closed and all(abs((p[2] if len(p)>2 else 0.0)) < 1e-12 for p in e.pts):
            try:
                from shapely.geometry import Polygon, Point as SPoint
                poly=Polygon([(float(p[0]),float(p[1])) for p in e.pts])
                if poly.is_valid and not poly.is_empty and poly.area > G.EPS:
                    amt=-float(d) if poly.contains(SPoint(float(side[0]),float(side[1]))) else float(d)
                    q=poly.buffer(amt, join_style=2)
                    if q.is_empty:return None
                    if q.geom_type=='MultiPolygon':
                        # AutoCAD does not invent a self-crossing loop; keep the largest valid island.
                        q=max(q.geoms,key=lambda z:z.area)
                    if q.geom_type=='Polygon' and q.area>G.EPS:
                        pts=list(q.exterior.coords)[:-1]
                        if len(pts)>=3:return e.clone(pts=[(float(x),float(y),0.0) for x,y in pts],closed=True)
                    return None
            except Exception:
                pass
        s = path_station(prims, side)
        q = path_point(prims, s)
        ta = math.radians(path_tangent(prims, s))
        left = G.cross(math.cos(ta), math.sin(ta), side[0] - q[0], side[1] - q[1]) >= 0
        out=_offset_poly(e, d if left else -d)
        # Refuse obviously invalid collapsed/reversed closed offsets.
        if out is not None and e.closed and abs(out.area()) < G.EPS:return None
        return out
    if isinstance(e,(Ellipse,Spline)):
        pts=e.points()
        if len(pts)<2:return None
        closed=(e.full() if isinstance(e,Ellipse) else e.closed)
        try:
            from shapely.geometry import Polygon,LineString,Point as SPoint
            xy=[(float(q[0]),float(q[1])) for q in pts]
            if closed:
                if G.dist(xy[0],xy[-1])<1e-9:xy=xy[:-1]
                poly=Polygon(xy)
                if not poly.is_valid or poly.is_empty:return None
                amt=-float(d) if poly.contains(SPoint(float(side[0]),float(side[1]))) else float(d)
                q=poly.buffer(amt,join_style=1,resolution=16)
                if q.is_empty:return None
                if q.geom_type=='MultiPolygon':q=max(q.geoms,key=lambda z:z.area)
                co=list(q.exterior.coords)[:-1]
                return Spline(fit=[(float(x),float(y)) for x,y in co],closed=True,**e.common()) if len(co)>=3 else None
            line=LineString(xy); s0=path_station(list(e.prims()),side);qq=path_point(list(e.prims()),s0);ta=math.radians(path_tangent(list(e.prims()),s0))
            left=G.cross(math.cos(ta),math.sin(ta),side[0]-qq[0],side[1]-qq[1])>=0
            q=line.offset_curve(float(d) if left else -float(d),join_style=1)
            if q.is_empty:return None
            if q.geom_type=='MultiLineString':q=max(q.geoms,key=lambda z:z.length)
            co=list(q.coords)
            return Spline(fit=[(float(x),float(y)) for x,y in co],closed=False,**e.common()) if len(co)>=2 else None
        except Exception:
            return None
    return None


def _offset_prim(pr, d):
    """d > 0 表示往行進方向左側偏移。"""
    if pr[0] == 'L':
        dx, dy = pr[3] - pr[1], pr[4] - pr[2]
        L = math.hypot(dx, dy)
        nx, ny = -dy / L * d, dx / L * d
        return ('L', pr[1] + nx, pr[2] + ny, pr[3] + nx, pr[4] + ny)
    ccw = len(pr) < 7 or pr[6]
    r = pr[3] - d if ccw else pr[3] + d
    if r <= G.EPS:
        return None
    return ('A', pr[1], pr[2], r, pr[4], pr[5], ccw)


def _offset_poly(e, d):
    src = e.prims()
    off = [_offset_prim(p, d) for p in src]
    if any(o is None for o in off):
        off = [o for o in off if o is not None]
    n = len(off)
    if n == 0:
        return None
    # 每個接點：相鄰兩段偏移後的延伸交點
    joints = []
    rng = range(n) if e.closed else range(n - 1)
    for i in rng:
        a, b = off[i], off[(i + 1) % n]
        ref = G.prim_end(a)
        ips = G.intersect(a, b, True, True)
        joints.append(min(ips, key=lambda p: G.dist(p, ref)) if ips else G.mid(ref, G.prim_start(b)))
    out = []
    for i in range(n):
        pr = off[i]
        s = joints[i - 1] if (e.closed or i > 0) else G.prim_start(pr)
        t = joints[i] if (e.closed or i < n - 1) else G.prim_end(pr)
        if pr[0] == 'L':
            if G.dist(s, t) > 1e-9:
                out.append(('L', s[0], s[1], t[0], t[1]))
        else:
            c = (pr[1], pr[2])
            ccw = len(pr) < 7 or pr[6]
            a_s, a_t = G.ang(c, s), G.ang(c, t)
            if ccw:
                span = (a_t - a_s) % 360.0
                if span > 1e-7:
                    out.append(('A', c[0], c[1], pr[3], a_s, span, True))
            else:
                span = (a_s - a_t) % 360.0
                if span > 1e-7:
                    out.append(('A', c[0], c[1], pr[3], a_t, span, False))
    return rebuild(e, out, e.closed) if out else None


# ---------------------------------------------------------------- 圓角 / 倒角
def _corner(l1, pk1, l2, pk2):
    a = ('L', l1.x1, l1.y1, l1.x2, l1.y2)
    b = ('L', l2.x1, l2.y1, l2.x2, l2.y2)
    ips = G.intersect(a, b, True, True)
    if not ips:
        return None
    I = ips[0]
    res = []
    for ln, pk, pr in ((l1, pk1, a), (l2, pk2, b)):
        ends = [(ln.x1, ln.y1), (ln.x2, ln.y2)]
        q = G.nearest_on_prim(pk, pr)[1]
        ref = q if G.dist(q, I) > 1e-9 else max(ends, key=lambda p: G.dist(p, I))
        ux, uy = ref[0] - I[0], ref[1] - I[1]
        L = math.hypot(ux, uy)
        ux, uy = ux / L, uy / L
        keep = max(ends, key=lambda p: (p[0] - I[0]) * ux + (p[1] - I[1]) * uy)
        res.append(((ux, uy), keep))
    return I, res[0], res[1]


def fillet_lines(l1, pk1, l2, pk2, r):
    """回傳 (新線1, 新線2, 弧或 None)；失敗回傳 None。"""
    c = _corner(l1, pk1, l2, pk2)
    if c is None:
        return None
    I, (u1, k1), (u2, k2) = c
    if r <= G.EPS:
        return (l1.clone(x1=I[0], y1=I[1], x2=k1[0], y2=k1[1]), l2.clone(x1=I[0], y1=I[1], x2=k2[0], y2=k2[1]), None)
    dot = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
    phi = math.acos(dot)
    if phi < 1e-6 or abs(phi - math.pi) < 1e-6:
        return None
    t = r / math.tan(phi / 2.0)
    if t > G.dist(I, k1) + 1e-9 or t > G.dist(I, k2) + 1e-9:
        return None
    t1 = (I[0] + u1[0] * t, I[1] + u1[1] * t)
    t2 = (I[0] + u2[0] * t, I[1] + u2[1] * t)
    bx, by = u1[0] + u2[0], u1[1] + u2[1]
    bl = math.hypot(bx, by)
    cc = (I[0] + bx / bl * r / math.sin(phi / 2.0), I[1] + by / bl * r / math.sin(phi / 2.0))
    a1, a2 = G.ang(cc, t1), G.ang(cc, t2)
    if (a2 - a1) % 360.0 > 180.0:
        a1, a2 = a2, a1
    arc = Arc(cx=cc[0], cy=cc[1], r=r, a0=a1, a1=a2, **l1.common())
    return (l1.clone(x1=t1[0], y1=t1[1], x2=k1[0], y2=k1[1]), l2.clone(x1=t2[0], y1=t2[1], x2=k2[0], y2=k2[1]), arc)


def chamfer_lines(l1, pk1, l2, pk2, d1, d2):
    c = _corner(l1, pk1, l2, pk2)
    if c is None:
        return None
    I, (u1, k1), (u2, k2) = c
    if d1 > G.dist(I, k1) + 1e-9 or d2 > G.dist(I, k2) + 1e-9:
        return None
    t1 = (I[0] + u1[0] * d1, I[1] + u1[1] * d1)
    t2 = (I[0] + u2[0] * d2, I[1] + u2[1] * d2)
    ch = Line(x1=t1[0], y1=t1[1], x2=t2[0], y2=t2[1], **l1.common()) if G.dist(t1, t2) > 1e-9 else None
    return (l1.clone(x1=t1[0], y1=t1[1], x2=k1[0], y2=k1[1]), l2.clone(x1=t2[0], y1=t2[1], x2=k2[0], y2=k2[1]), ch)


def fillet_polyline(e, r=None, d1=None, d2=None):
    """把聚合線所有直線轉角做圓角（給 r）或倒角（給 d1, d2）。"""
    pts = e.pts
    n = len(pts)
    out = []
    count = 0
    for i in range(n):
        p = pts[i]
        if not e.closed and i in (0, n - 1):
            out.append(p)
            continue
        a, b = pts[(i - 1) % n], pts[(i + 1) % n]
        if abs(a[2]) > 1e-12 or abs(p[2]) > 1e-12:
            out.append(p)
            continue
        la, lb = G.dist(a, p), G.dist(p, b)
        if la < G.EPS or lb < G.EPS:
            out.append(p)
            continue
        u1 = ((a[0] - p[0]) / la, (a[1] - p[1]) / la)
        u2 = ((b[0] - p[0]) / lb, (b[1] - p[1]) / lb)
        phi = math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1])))
        if phi < 1e-6 or abs(phi - math.pi) < 1e-6:
            out.append(p)
            continue
        if r is not None:
            ta = tb = r / math.tan(phi / 2.0)
            turn = G.cross(-u1[0], -u1[1], u2[0], u2[1])
            bulge = math.tan((math.pi - phi) / 4.0) * (1.0 if turn > 0 else -1.0)
        else:
            ta, tb, bulge = d1, d2, 0.0
        if ta > la / 2.0 + 1e-9 or tb > lb / 2.0 + 1e-9 or ta <= 0:
            out.append(p)
            continue
        out.append((p[0] + u1[0] * ta, p[1] + u1[1] * ta, bulge))
        out.append((p[0] + u2[0] * tb, p[1] + u2[1] * tb, 0.0))
        count += 1
    return e.clone(pts=out), count


# ---------------------------------------------------------------- 拉伸
def stretch_entity(e, rect, dx, dy):
    inside = lambda p: rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]
    mv = lambda p: (p[0] + dx, p[1] + dy)
    dps = e.def_points()
    if dps and all(inside(p) for p in dps):
        return e.transformed(G.m_translate(dx, dy))
    if isinstance(e, Line):
        a, b = (e.x1, e.y1), (e.x2, e.y2)
        if inside(a):
            a = mv(a)
        if inside(b):
            b = mv(b)
        return e.clone(x1=a[0], y1=a[1], x2=b[0], y2=b[1])
    if isinstance(e, Polyline):
        return e.clone(pts=[(p[0] + dx, p[1] + dy, p[2]) if inside(p) else p for p in e.pts])
    if isinstance(e, Arc):
        s, t = e.ends()
        m = e.midpoint()
        s2, t2 = (mv(s) if inside(s) else s), (mv(t) if inside(t) else t)
        if s2 == s and t2 == t:
            return e
        a = G.arc_3p(s2, m, t2)
        return e.clone(cx=a[0], cy=a[1], r=a[2], a0=a[3], a1=a[4]) if a else e
    if isinstance(e, Dim):
        return e.clone(pts=[mv(p) if inside(p) else p for p in e.pts])
    if isinstance(e, Hatch):
        return e.clone(loops=[[mv(p) if inside(p) else p for p in lp] for lp in e.loops])
    if isinstance(e, Spline):
        return e.clone(fit=[mv(p) if inside(p) else p for p in e.fit],
                       ctrl=[mv(p) if inside(p) else p for p in e.ctrl])
    return e


# ---------------------------------------------------------------- 接合 / 分解
def join_entities(ents):
    """把端點相接的圖元接合。共線 Line 依 AutoCAD 行為優先合成單一 Line。"""
    # AutoCAD JOIN: two or more collinear connected lines remain a LINE, not a polyline.
    lines = [e for e in ents if isinstance(e, Line)]
    if len(lines) >= 2 and len(lines) == len(ents):
        ux, uy = lines[0].x2-lines[0].x1, lines[0].y2-lines[0].y1
        L = math.hypot(ux, uy)
        if L > G.EPS:
            ux, uy = ux/L, uy/L
            ox, oy = lines[0].x1, lines[0].y1
            if all(abs(G.cross(ux,uy,e.x1-ox,e.y1-oy)) < 1e-6 and
                   abs(G.cross(ux,uy,e.x2-ox,e.y2-oy)) < 1e-6 for e in lines):
                ts=[]
                for e in lines:
                    ts += [((e.x1-ox)*ux+(e.y1-oy)*uy), ((e.x2-ox)*ux+(e.y2-oy)*uy)]
                lo,hi=min(ts),max(ts)
                # Require the projected intervals to form one connected union.
                iv=[]
                for e in lines:
                    a=(e.x1-ox)*ux+(e.y1-oy)*uy; b=(e.x2-ox)*ux+(e.y2-oy)*uy
                    iv.append(tuple(sorted((a,b))))
                iv.sort(); end=iv[0][1]; connected=True
                for a,b in iv[1:]:
                    if a > end + 1e-6: connected=False; break
                    end=max(end,b)
                if connected:
                    e0=lines[0]
                    return [Line(x1=ox+ux*lo,y1=oy+uy*lo,x2=ox+ux*hi,y2=oy+uy*hi,**e0.common())], list(lines)
    chains = []
    for e in ents:
        if isinstance(e, (Line, Arc)) or (isinstance(e, Polyline) and not e.closed):
            ps = list(e.prims())
            if ps:
                chains.append((e, ps))
    used, out = [], []
    tol = 1e-6
    while chains:
        e0, cur = chains.pop(0)
        members = [e0]
        grew = True
        while grew:
            grew = False
            s, t = G.prim_start(cur[0]), G.prim_end(cur[-1])
            for i, (e, ps) in enumerate(chains):
                a, b = G.prim_start(ps[0]), G.prim_end(ps[-1])
                if G.dist(t, a) < tol:
                    cur = cur + ps
                elif G.dist(t, b) < tol:
                    cur = cur + reverse_prims(ps)
                elif G.dist(s, b) < tol:
                    cur = ps + cur
                elif G.dist(s, a) < tol:
                    cur = reverse_prims(ps) + cur
                else:
                    continue
                members.append(e)
                chains.pop(i)
                grew = True
                break
        if len(members) < 2:
            continue
        closed = G.dist(G.prim_start(cur[0]), G.prim_end(cur[-1])) < tol
        pts = G.prims_to_poly(cur)
        if closed:
            pts = pts[:-1]
        out.append(Polyline(pts=pts, closed=closed, **e0.common()))
        used += members
    return out, used


def explode_entity(doc, e):
    """分解一層。無法分解回傳 None。"""
    kw = e.common()
    if isinstance(e, Polyline):
        out = []
        for pr in e.prims():
            if pr[0] == 'L':
                out.append(Line(x1=pr[1], y1=pr[2], x2=pr[3], y2=pr[4], **kw))
            else:
                out.append(Arc(cx=pr[1], cy=pr[2], r=pr[3], a0=pr[4] % 360.0, a1=(pr[4] + pr[5]) % 360.0, **kw))
        return out
    if isinstance(e, Dim):
        return list(e.parts())
    if isinstance(e, MText):
        rows, _, _, col, _ = e.layout()
        m = G.m_rotate((0, 0), e.rot)
        out = []
        for dx, dy, s in rows:
            ax = {0: 0.0, 1: 0.0, 2: 0.0}[col]
            q = G.m_apply(m, (ax, dy))
            out.append(Text(x=e.x + q[0], y=e.y + q[1], text=s, height=e.height, rot=e.rot, halign=col, **kw))
        return out
    if isinstance(e, Array):
        return list(e.parts())
    if isinstance(e, Insert):
        blk = doc.blocks.get(e.name)
        if blk is None:
            return None
        m = e.matrix(blk)
        out = []
        for be in blk.entities:
            t = be.transformed(m)
            ch = {}
            if t.layer == "0":
                ch["layer"] = e.layer
            if t.color == 0:
                ch["color"] = e.color
            out.append(t.clone(**ch) if ch else t)
        return out
    return None


# ---------------------------------------------------------------- 填充線邊界
def closed_outline(e):
    """封閉圖元的外框點列；非封閉回傳 None。"""
    if isinstance(e, Circle):
        return G.flatten_prims(e.prims(), 5.0)[:-1]
    if isinstance(e, Polyline) and e.closed and len(e.pts) >= 3:
        pts = G.flatten_prims(e.prims(), 5.0)
        if len(pts) > 1 and G.dist(pts[0], pts[-1]) < 1e-9:
            pts = pts[:-1]
        return pts
    if isinstance(e, Ellipse) and e.full():
        return e.points()[:-1]
    if isinstance(e, Spline) and (e.closed or (len(e.points()) > 2 and G.dist(e.points()[0], e.points()[-1]) < 1e-9)):
        return e.points()[:-1]
    return None


def find_boundary(doc, p, view_rect=None, max_segs=4000):
    """找出包住點 p 的最小封閉區域。回傳 loops（外框 + 島嶼）或 None。"""
    segs = []
    for e in doc.entities:
        if not doc.visible(e) or isinstance(e, (Hatch, Dim, Text, MText, Point, Solid3D)):
            continue
        b = doc.bbox(e)
        if view_rect and b and (b[2] < view_rect[0] or b[0] > view_rect[2] or b[3] < view_rect[1] or b[1] > view_rect[3]):
            continue
        for leaf in doc.expand(e):
            if isinstance(leaf, (Hatch, Text, MText, Point)):
                continue
            prims = leaf.prims()
            if isinstance(leaf, XLine) and view_rect:
                continue
            pts = None
            for pr in prims:
                if pr[0] == 'L':
                    segs.append((pr[1], pr[2], pr[3], pr[4]))
                else:
                    pts = G.flatten_prims([pr], 6.0)
                    for i in range(len(pts) - 1):
                        segs.append((pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]))
            if len(segs) > max_segs:
                break
    outer = _trace_face(segs, p) if 0 < len(segs) <= max_segs else None
    if outer is None:
        # 後備方案：直接找包住 p 的最小封閉圖元
        best = None
        for e in doc.entities:
            if not doc.visible(e) or isinstance(e, Solid3D):
                continue
            o = closed_outline(e)
            if o and G.point_in_poly(p, o):
                a = abs(G.poly_area(o))
                if best is None or a < best[0]:
                    best = (a, o)
        if best is None:
            return None
        outer = best[1]
    loops = [outer]
    area = abs(G.poly_area(outer))
    for e in doc.entities:
        if not doc.visible(e) or isinstance(e, Solid3D):
            continue
        o = closed_outline(e)
        if not o or G.point_in_poly(p, o):
            continue
        if abs(G.poly_area(o)) < area * 0.999 and all(G.point_in_poly(q, outer) for q in o[::max(1, len(o) // 8)]):
            loops.append(o)
    return loops


def _trace_face(segs, p):
    ext = max(max(abs(s[0]), abs(s[1]), abs(s[2]), abs(s[3])) for s in segs) or 1.0
    tol = ext * 1e-9 + 1e-9
    # 1) 在交點處切開
    order = sorted(range(len(segs)), key=lambda i: min(segs[i][0], segs[i][2]))
    cuts = [[0.0, 1.0] for _ in segs]
    for ii, i in enumerate(order):
        a = segs[i]
        amax = max(a[0], a[2])
        aymin, aymax = min(a[1], a[3]), max(a[1], a[3])
        for j in order[ii + 1:]:
            b = segs[j]
            if min(b[0], b[2]) > amax + tol:
                break
            if max(b[1], b[3]) < aymin - tol or min(b[1], b[3]) > aymax + tol:
                continue
            den = (a[0] - a[2]) * (b[1] - b[3]) - (a[1] - a[3]) * (b[0] - b[2])
            if abs(den) < 1e-14:
                continue
            t = ((a[0] - b[0]) * (b[1] - b[3]) - (a[1] - b[1]) * (b[0] - b[2])) / den
            u = ((a[0] - b[0]) * (a[1] - a[3]) - (a[1] - b[1]) * (a[0] - a[2])) / den
            if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
                cuts[i].append(min(1.0, max(0.0, t)))
                cuts[j].append(min(1.0, max(0.0, u)))
    # 2) 建圖
    q = max(tol, ext * 1e-7)
    key = lambda x, y: (round(x / q), round(y / q))
    pos, adj = {}, {}
    for i, s in enumerate(segs):
        ts = sorted(set(cuts[i]))
        prev = None
        for t in ts:
            x, y = s[0] + (s[2] - s[0]) * t, s[1] + (s[3] - s[1]) * t
            k = key(x, y)
            pos.setdefault(k, (x, y))
            if prev is not None and prev != k:
                adj.setdefault(prev, set()).add(k)
                adj.setdefault(k, set()).add(prev)
            prev = k
    # 3) 去掉懸空的線頭
    stack = [k for k, v in adj.items() if len(v) <= 1]
    while stack:
        k = stack.pop()
        nb = adj.pop(k, None)
        if nb is None:
            continue
        for o in nb:
            if o in adj:
                adj[o].discard(k)
                if len(adj[o]) <= 1:
                    stack.append(o)
    if not adj:
        return None
    # 4) 從 p 往右射線，找最近的邊
    best = None
    seen = set()
    for u, nb in adj.items():
        for v in nb:
            if (v, u) in seen:
                continue
            seen.add((u, v))
            (x1, y1), (x2, y2) = pos[u], pos[v]
            if (y1 > p[1]) == (y2 > p[1]):
                continue
            x = x1 + (p[1] - y1) * (x2 - x1) / (y2 - y1)
            if x > p[0] and (best is None or x < best[0]):
                best = (x, u, v)
    if best is None:
        return None
    _, u, v = best
    if G.cross(pos[v][0] - pos[u][0], pos[v][1] - pos[u][1], p[0] - pos[u][0], p[1] - pos[u][1]) < 0:
        u, v = v, u
    # 5) 沿著面的邊界走（面保持在左手邊）
    start = (u, v)
    loop = [pos[u]]
    a, b = u, v
    for _ in range(len(pos) * 4 + 16):
        loop.append(pos[b])
        back = math.atan2(pos[a][1] - pos[b][1], pos[a][0] - pos[b][0])
        nxt, bestd = None, None
        for c in adj[b]:
            if c == a and len(adj[b]) > 1:
                continue
            d = (back - math.atan2(pos[c][1] - pos[b][1], pos[c][0] - pos[b][0])) % (2 * math.pi)
            if d < 1e-12:
                d = 2 * math.pi
            if bestd is None or d < bestd:
                nxt, bestd = c, d
        if nxt is None:
            return None
        a, b = b, nxt
        if (a, b) == start:
            break
    else:
        return None
    loop = loop[:-1] if len(loop) > 1 and loop[0] == loop[-1] else loop
    if len(loop) < 3 or G.poly_area(loop) <= 0 or not G.point_in_poly(p, loop):
        return None
    return loop
