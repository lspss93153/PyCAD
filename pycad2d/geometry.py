# SPDX-License-Identifier: GPL-3.0-only
"""純數學幾何工具（不依賴 Qt）。

基本圖元 (prim) 有兩種：
    ('L', x1, y1, x2, y2)                    線段，方向 p1 -> p2
    ('A', cx, cy, r, a0, span, ccw=True)     圓弧，從 a0 逆時針掃 span 度 (0 < span <= 360)
                                             ccw=False 表示行進方向是從終點走回起點
角度一律用「度」，逆時針為正。
"""
import math

EPS = 1e-9
TOL = 1e-7


# ---------------------------------------------------------------- 基本向量
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def ang(a, b):
    """a 指向 b 的方向角（度，0~360）。"""
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360.0


def polar(p, a_deg, d):
    r = math.radians(a_deg)
    return (p[0] + d * math.cos(r), p[1] + d * math.sin(r))


def mid(a, b):
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def cross(ax, ay, bx, by):
    return ax * by - ay * bx


# ---------------------------------------------------------------- 仿射矩陣
# m = (a, b, c, d, e, f) :  x' = a*x + c*y + e ,  y' = b*x + d*y + f
IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def m_apply(m, p):
    return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])


def m_vec(m, v):
    return (m[0] * v[0] + m[2] * v[1], m[1] * v[0] + m[3] * v[1])


def m_mul(m2, m1):
    """先套 m1 再套 m2。"""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a2 * a1 + c2 * b1, b2 * a1 + d2 * b1,
            a2 * c1 + c2 * d1, b2 * c1 + d2 * d1,
            a2 * e1 + c2 * f1 + e2, b2 * e1 + d2 * f1 + f2)


def m_translate(dx, dy):
    return (1.0, 0.0, 0.0, 1.0, dx, dy)


def m_rotate(c, deg):
    r = math.radians(deg)
    co, si = math.cos(r), math.sin(r)
    return (co, si, -si, co, c[0] - co * c[0] + si * c[1], c[1] - si * c[0] - co * c[1])


def m_scale(c, sx, sy=None):
    if sy is None:
        sy = sx
    return (sx, 0.0, 0.0, sy, c[0] * (1 - sx), c[1] * (1 - sy))


def m_mirror(p1, p2):
    t = 2 * math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    a, b = math.cos(t), math.sin(t)
    c, d = b, -a
    return (a, b, c, d, p1[0] - (a * p1[0] + c * p1[1]), p1[1] - (b * p1[0] + d * p1[1]))


def m_info(m):
    """回傳 (scale, rot_deg, mirrored, uniform)。"""
    a, b, c, d = m[0], m[1], m[2], m[3]
    sx, sy = math.hypot(a, b), math.hypot(c, d)
    det = a * d - b * c
    uniform = abs(sx - sy) <= 1e-9 * max(1.0, sx) and abs(a * c + b * d) <= 1e-9 * max(1.0, sx * sy)
    return (math.sqrt(abs(det)), math.degrees(math.atan2(b, a)), det < 0, uniform)


# ---------------------------------------------------------------- 圓弧工具
def on_arc(a, a0, span):
    if span >= 360.0 - TOL:
        return True
    d = (a - a0) % 360.0
    return d <= span + 1e-6 or d >= 360.0 - 1e-6


def arc_pts(pr):
    """圓弧 prim 的幾何起點與終點（逆時針定義，不考慮行進方向）。"""
    _, cx, cy, r, a0, span = pr[:6]
    return polar((cx, cy), a0, r), polar((cx, cy), a0 + span, r)


def circle_3p(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < EPS:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy, dist((ux, uy), a))


def arc_3p(a, b, c):
    """三點定弧，回傳 (cx, cy, r, a0, a1)（a0 -> a1 逆時針）。"""
    cc = circle_3p(a, b, c)
    if cc is None:
        return None
    ux, uy, r = cc
    aa, ab, ac = ang((ux, uy), a), ang((ux, uy), b), ang((ux, uy), c)
    if (ab - aa) % 360.0 <= (ac - aa) % 360.0:
        return (ux, uy, r, aa, ac)
    return (ux, uy, r, ac, aa)


def bulge_arc(p1, p2, bulge):
    """聚合線弧段 -> ('A', cx, cy, r, a0, span, ccw)。"""
    d = dist(p1, p2)
    theta = 4.0 * math.atan(bulge)
    h = (d / 2.0) / math.tan(theta / 2.0)
    mx, my = mid(p1, p2)
    nx, ny = -(p2[1] - p1[1]) / d, (p2[0] - p1[0]) / d
    c = (mx + nx * h, my + ny * h)
    r = dist(c, p1)
    span = abs(math.degrees(theta))
    if bulge > 0:
        return ('A', c[0], c[1], r, ang(c, p1), span, True)
    return ('A', c[0], c[1], r, ang(c, p2), span, False)


def poly_prims(pts, closed):
    """pts: [(x, y, bulge), ...] -> 有方向的 prim 清單。"""
    out = []
    n = len(pts)
    for i in range(n if closed else n - 1):
        p, q = pts[i], pts[(i + 1) % n]
        if dist(p, q) < EPS:
            continue
        b = p[2] if len(p) > 2 else 0.0
        if abs(b) < 1e-12:
            out.append(('L', p[0], p[1], q[0], q[1]))
        else:
            out.append(bulge_arc(p, q, b))
    return out


def prims_to_poly(prims):
    """有方向的 prim 清單 -> [(x, y, bulge), ...]（含最後一點）。"""
    pts = []
    last = None
    for pr in prims:
        s, e = prim_start(pr), prim_end(pr)
        b = 0.0
        if pr[0] == 'A':
            b = math.tan(math.radians(pr[5]) / 4.0)
            if len(pr) > 6 and not pr[6]:
                b = -b
        pts.append((s[0], s[1], b))
        last = e
    if last is not None:
        pts.append((last[0], last[1], 0.0))
    return pts


# ---------------------------------------------------------------- prim 參數化
def prim_start(pr):
    if pr[0] == 'L':
        return (pr[1], pr[2])
    s, e = arc_pts(pr)
    return s if (len(pr) < 7 or pr[6]) else e


def prim_end(pr):
    if pr[0] == 'L':
        return (pr[3], pr[4])
    s, e = arc_pts(pr)
    return e if (len(pr) < 7 or pr[6]) else s


def prim_len(pr):
    if pr[0] == 'L':
        return math.hypot(pr[3] - pr[1], pr[4] - pr[2])
    return pr[3] * math.radians(pr[5])


def prim_point(pr, s):
    """沿行進方向距離 s 處的點。"""
    if pr[0] == 'L':
        L = prim_len(pr)
        t = s / L if L > EPS else 0.0
        return (pr[1] + (pr[3] - pr[1]) * t, pr[2] + (pr[4] - pr[2]) * t)
    _, cx, cy, r, a0, span = pr[:6]
    da = math.degrees(s / r) if r > EPS else 0.0
    if len(pr) < 7 or pr[6]:
        return polar((cx, cy), a0 + da, r)
    return polar((cx, cy), a0 + span - da, r)


def prim_station(pr, p):
    """點 p（假設在 prim 上）沿行進方向的距離。"""
    if pr[0] == 'L':
        dx, dy = pr[3] - pr[1], pr[4] - pr[2]
        L2 = dx * dx + dy * dy
        if L2 < EPS:
            return 0.0
        t = ((p[0] - pr[1]) * dx + (p[1] - pr[2]) * dy) / L2
        return max(0.0, min(1.0, t)) * math.sqrt(L2)
    _, cx, cy, r, a0, span = pr[:6]
    d = (ang((cx, cy), p) - a0) % 360.0
    if d > span:
        d = span if d - span < (360.0 - d) else 0.0
    if not (len(pr) < 7 or pr[6]):
        d = span - d
    return r * math.radians(d)


def prim_tangent(pr, s):
    """行進方向的切線角（度）。"""
    if pr[0] == 'L':
        return ang((pr[1], pr[2]), (pr[3], pr[4]))
    p = prim_point(pr, s)
    a = ang((pr[1], pr[2]), p)
    return (a + 90.0) % 360.0 if (len(pr) < 7 or pr[6]) else (a - 90.0) % 360.0


def sub_prim(pr, s0, s1):
    """擷取 prim 上 [s0, s1] 這一段（保留行進方向）。"""
    if s1 - s0 < 1e-9:
        return None
    if pr[0] == 'L':
        a, b = prim_point(pr, s0), prim_point(pr, s1)
        return ('L', a[0], a[1], b[0], b[1])
    _, cx, cy, r, a0, span = pr[:6]
    ccw = len(pr) < 7 or pr[6]
    d0, d1 = math.degrees(s0 / r), math.degrees(s1 / r)
    if ccw:
        return ('A', cx, cy, r, (a0 + d0) % 360.0, d1 - d0, True)
    return ('A', cx, cy, r, (a0 + span - d1) % 360.0, d1 - d0, False)


def nearest_on_prim(p, pr):
    """回傳 (距離, 最近點)。"""
    if pr[0] == 'L':
        dx, dy = pr[3] - pr[1], pr[4] - pr[2]
        L2 = dx * dx + dy * dy
        if L2 < EPS:
            q = (pr[1], pr[2])
        else:
            t = max(0.0, min(1.0, ((p[0] - pr[1]) * dx + (p[1] - pr[2]) * dy) / L2))
            q = (pr[1] + t * dx, pr[2] + t * dy)
        return dist(p, q), q
    _, cx, cy, r, a0, span = pr[:6]
    c = (cx, cy)
    a = ang(c, p) if dist(c, p) > EPS else a0
    if on_arc(a, a0, span):
        q = polar(c, a, r)
        return dist(p, q), q
    s, e = arc_pts(pr)
    ds, de = dist(p, s), dist(p, e)
    return (ds, s) if ds <= de else (de, e)


def prim_bbox(pr):
    if pr[0] == 'L':
        return (min(pr[1], pr[3]), min(pr[2], pr[4]), max(pr[1], pr[3]), max(pr[2], pr[4]))
    _, cx, cy, r, a0, span = pr[:6]
    s, e = arc_pts(pr)
    xs, ys = [s[0], e[0]], [s[1], e[1]]
    for q in (0.0, 90.0, 180.0, 270.0):
        if on_arc(q, a0, span):
            x, y = polar((cx, cy), q, r)
            xs.append(x)
            ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------- 交點
def _ll(pa, pb, ea, eb):
    x1, y1, x2, y2 = pa[1:5]
    x3, y3, x4, y4 = pb[1:5]
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-12:
        return []
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / den
    if not ea and not (-TOL <= t <= 1 + TOL):
        return []
    if not eb and not (-TOL <= u <= 1 + TOL):
        return []
    return [(x1 + t * (x2 - x1), y1 + t * (y2 - y1))]


def _la(pl, pa, el, ea):
    x1, y1, x2, y2 = pl[1:5]
    _, cx, cy, r, a0, span = pa[:6]
    dx, dy = x2 - x1, y2 - y1
    A = dx * dx + dy * dy
    if A < EPS:
        return []
    B = 2 * (dx * (x1 - cx) + dy * (y1 - cy))
    C = (x1 - cx) ** 2 + (y1 - cy) ** 2 - r * r
    disc = B * B - 4 * A * C
    if disc < -1e-9 * max(1.0, B * B):
        return []
    sq = math.sqrt(max(0.0, disc))
    out = []
    for t in ({(-B) / (2 * A)} if sq < 1e-9 else ((-B - sq) / (2 * A), (-B + sq) / (2 * A))):
        if not el and not (-TOL <= t <= 1 + TOL):
            continue
        p = (x1 + t * dx, y1 + t * dy)
        if ea or on_arc(ang((cx, cy), p), a0, span):
            out.append(p)
    return out


def _aa(p1, p2, e1, e2):
    _, x1, y1, r1, a1, s1 = p1[:6]
    _, x2, y2, r2, a2, s2 = p2[:6]
    d = math.hypot(x2 - x1, y2 - y1)
    if d < EPS or d > r1 + r2 + TOL or d < abs(r1 - r2) - TOL:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, r1 * r1 - a * a))
    mx, my = x1 + a * (x2 - x1) / d, y1 + a * (y2 - y1) / d
    cand = [(mx, my)] if h < 1e-9 else [(mx + h * (y2 - y1) / d, my - h * (x2 - x1) / d),
                                        (mx - h * (y2 - y1) / d, my + h * (x2 - x1) / d)]
    return [p for p in cand
            if (e1 or on_arc(ang((x1, y1), p), a1, s1)) and (e2 or on_arc(ang((x2, y2), p), a2, s2))]


def intersect(pa, pb, ext_a=False, ext_b=False):
    """兩個 prim 的交點。ext=True 時把線視為無限長、弧視為整圓。"""
    if pa[0] == 'L' and pb[0] == 'L':
        return _ll(pa, pb, ext_a, ext_b)
    if pa[0] == 'L':
        return _la(pa, pb, ext_a, ext_b)
    if pb[0] == 'L':
        return _la(pb, pa, ext_b, ext_a)
    return _aa(pa, pb, ext_a, ext_b)


def perp_foot(base, pr):
    """從 base 到 prim 的垂足（可能不存在）。"""
    if pr[0] == 'L':
        dx, dy = pr[3] - pr[1], pr[4] - pr[2]
        L2 = dx * dx + dy * dy
        if L2 < EPS:
            return []
        t = ((base[0] - pr[1]) * dx + (base[1] - pr[2]) * dy) / L2
        return [(pr[1] + t * dx, pr[2] + t * dy)] if -TOL <= t <= 1 + TOL else []
    c = (pr[1], pr[2])
    if dist(base, c) < EPS:
        return []
    a = ang(c, base)
    return [polar(c, x, pr[3]) for x in (a, a + 180.0) if on_arc(x % 360.0, pr[4], pr[5])]


def tangent_pts(base, pr):
    if pr[0] != 'A':
        return []
    c, r = (pr[1], pr[2]), pr[3]
    d = dist(base, c)
    if d <= r + EPS:
        return []
    a = ang(c, base)
    b = math.degrees(math.acos(r / d))
    return [polar(c, x, r) for x in (a + b, a - b) if on_arc(x % 360.0, pr[4], pr[5])]


# ---------------------------------------------------------------- 多邊形
def poly_area(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def point_in_poly(p, pts):
    x, y = p
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i][0], pts[i][1]
        xj, yj = pts[j][0], pts[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def flatten_prims(prims, seg_deg=7.5):
    """把 prim 清單攤平成點列（弧以線段近似）。"""
    pts = []
    for pr in prims:
        if pr[0] == 'L':
            if not pts or dist(pts[-1], (pr[1], pr[2])) > 1e-9:
                pts.append((pr[1], pr[2]))
            pts.append((pr[3], pr[4]))
        else:
            n = max(2, int(math.ceil(pr[5] / seg_deg)))
            L = prim_len(pr)
            for k in range(n + 1):
                q = prim_point(pr, L * k / n)
                if not pts or dist(pts[-1], q) > 1e-9:
                    pts.append(q)
    return pts


def seg_hits_rect(x1, y1, x2, y2, r):
    """線段是否碰到矩形 r=(minx, miny, maxx, maxy)。"""
    rx0, ry0, rx1, ry1 = r
    if (rx0 <= x1 <= rx1 and ry0 <= y1 <= ry1) or (rx0 <= x2 <= rx1 and ry0 <= y2 <= ry1):
        return True
    if max(x1, x2) < rx0 or min(x1, x2) > rx1 or max(y1, y2) < ry0 or min(y1, y2) > ry1:
        return False
    seg = ('L', x1, y1, x2, y2)
    for e in (('L', rx0, ry0, rx1, ry0), ('L', rx1, ry0, rx1, ry1),
              ('L', rx1, ry1, rx0, ry1), ('L', rx0, ry1, rx0, ry0)):
        if _ll(seg, e, False, False):
            return True
    return False


def prim_hits_rect(pr, r):
    if pr[0] == 'L':
        return seg_hits_rect(pr[1], pr[2], pr[3], pr[4], r)
    b = prim_bbox(pr)
    if b[2] < r[0] or b[0] > r[2] or b[3] < r[1] or b[1] > r[3]:
        return False
    s, e = arc_pts(pr)
    for q in (s, e):
        if r[0] <= q[0] <= r[2] and r[1] <= q[1] <= r[3]:
            return True
    for ed in (('L', r[0], r[1], r[2], r[1]), ('L', r[2], r[1], r[2], r[3]),
               ('L', r[2], r[3], r[0], r[3]), ('L', r[0], r[3], r[0], r[1])):
        if _la(ed, pr, False, False):
            return True
    return False


# ---------------------------------------------------------------- 橢圓 / 雲形線
def ellipse_axes(u, v):
    """由共軛半徑 u, v 求主軸。回傳 (major, ratio, t_shift, flipped)。
    原參數 t 對應新參數 s： s = (t - t_shift)，flipped 時 s = -(t - t_shift)。"""
    uu = u[0] * u[0] + u[1] * u[1]
    vv = v[0] * v[0] + v[1] * v[1]
    uv = u[0] * v[0] + u[1] * v[1]
    t0 = 0.5 * math.atan2(2 * uv, uu - vv)
    c, s = math.cos(t0), math.sin(t0)
    ma = (u[0] * c + v[0] * s, u[1] * c + v[1] * s)
    mi = (-u[0] * s + v[0] * c, -u[1] * s + v[1] * c)
    shift = t0
    if math.hypot(*mi) > math.hypot(*ma):
        ma, mi = mi, (-ma[0], -ma[1])
        shift = t0 + math.pi / 2
    lm = math.hypot(*ma)
    ratio = math.hypot(*mi) / lm if lm > EPS else 1.0
    flipped = cross(ma[0], ma[1], mi[0], mi[1]) < 0
    return ma, ratio, shift, flipped


def ellipse_points(cx, cy, mx, my, ratio, t0, t1, n=None):
    span = (t1 - t0) % (2 * math.pi)
    if span < 1e-9:
        span = 2 * math.pi
    if n is None:
        n = max(12, int(math.ceil(96 * span / (2 * math.pi))))
    nx, ny = -my * ratio, mx * ratio
    out = []
    for k in range(n + 1):
        t = t0 + span * k / n
        c, s = math.cos(t), math.sin(t)
        out.append((cx + mx * c + nx * s, cy + my * c + ny * s))
    return out


def catmull_rom(fit, closed=False, per=12):
    n = len(fit)
    if n < 3:
        return list(fit)
    pts = []

    def P(i):
        if closed:
            return fit[i % n]
        return fit[max(0, min(n - 1, i))]

    for i in range(n if closed else n - 1):
        p0, p1, p2, p3 = P(i - 1), P(i), P(i + 1), P(i + 2)
        for k in range(per):
            t = k / per
            t2, t3 = t * t, t * t * t
            pts.append(tuple(
                0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2 +
                       (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in (0, 1)))
    pts.append(tuple(fit[0][:2]) if closed else tuple(fit[-1][:2]))
    return pts


def bspline_points(ctrl, knots, degree, n=None):
    """以 de Boor 演算法取樣 B-spline（忽略權重）。"""
    m = len(ctrl)
    if m < 2:
        return [tuple(c[:2]) for c in ctrl]
    p = max(1, min(degree, m - 1))
    if len(knots) != m + p + 1:
        knots = [0.0] * (p + 1) + [float(i) for i in range(1, m - p)] + [float(m - p)] * (p + 1)
    lo, hi = knots[p], knots[m]
    if hi - lo < EPS:
        return [tuple(c[:2]) for c in ctrl]
    if n is None:
        n = max(24, m * 8)
    out = []
    for i in range(n + 1):
        u = lo + (hi - lo) * i / n
        if i == n:
            u = hi - (hi - lo) * 1e-12
        k = p
        for j in range(p, m):
            if knots[j] <= u < knots[j + 1]:
                k = j
                break
        else:
            k = m - 1
        d = [list(ctrl[j + k - p][:2]) for j in range(p + 1)]
        for r in range(1, p + 1):
            for j in range(p, r - 1, -1):
                den = knots[j + 1 + k - r] - knots[j + k - p]
                al = 0.0 if abs(den) < EPS else (u - knots[j + k - p]) / den
                d[j][0] = (1 - al) * d[j - 1][0] + al * d[j][0]
                d[j][1] = (1 - al) * d[j - 1][1] + al * d[j][1]
        out.append((d[p][0], d[p][1]))
    return out
