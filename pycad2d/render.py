# SPDX-License-Identifier: GPL-3.0-only
"""繪製引擎：螢幕、PDF、SVG、PNG 共用同一套繪圖程式。"""
import math
from PySide6.QtCore import Qt, QPointF, QRectF, QMarginsF, QSize
from PySide6.QtGui import (QPainter, QPen, QColor, QBrush, QFont, QFontMetricsF, QPainterPath, QTransform,
                           QPolygonF, QImage, QPageSize, QPageLayout, QPdfWriter, QFontDatabase)
from . import geometry as G
from .model import (Line, Circle, Arc, Polyline, Ellipse, Spline, Point, Text, MText, Hatch, XLine, Solid3D, aci_rgb)

HATCH_PATTERNS = {
    "SOLID": [],
    "ANSI31": [(45.0, 3.175)],
    "ANSI32": [(45.0, 6.35), (135.0, 6.35)],
    "ANSI33": [(45.0, 3.175), (135.0, 9.525)],
    "ANSI34": [(45.0, 3.175), (135.0, 12.7)],
    "ANSI35": [(45.0, 3.175), (135.0, 6.35)],
    "ANSI36": [(45.0, 4.7625), (135.0, 9.525)],
    "ANSI37": [(45.0, 3.175), (135.0, 3.175)],
    "ANSI38": [(45.0, 6.35), (135.0, 3.175)],
    "LINE": [(0.0, 3.175)],
    "NET": [(0.0, 3.175), (90.0, 3.175)],
    "NET3": [(0.0, 6.35), (60.0, 6.35), (120.0, 6.35)],
    "CROSS45": [(45.0, 6.35), (135.0, 6.35)],
    "BRICK": [(0.0, 6.35), (90.0, 12.7)],
    "AR-B816": [(0.0, 8.0), (90.0, 16.0)],
    "AR-B816C": [(0.0, 8.0), (90.0, 16.0), (45.0, 32.0)],
    "AR-CONC": [(0.0, 5.0), (60.0, 8.0), (120.0, 13.0)],
    "AR-HBONE": [(45.0, 6.35), (135.0, 12.7), (0.0, 25.4)],
    "AR-PARQ1": [(45.0, 4.0), (135.0, 12.0), (0.0, 24.0)],
    "CLAY": [(0.0, 4.7625), (90.0, 9.525)],
    "CORK": [(0.0, 5.0), (45.0, 10.0), (135.0, 10.0)],
    "DASH": [(0.0, 6.35)],
    "DOLMIT": [(0.0, 6.35), (45.0, 12.7)],
    "DOTS": [(0.0, 9.525), (90.0, 9.525)],
    "EARTH": [(0.0, 6.35), (45.0, 12.7), (135.0, 12.7)],
    "FLEX": [(0.0, 12.7), (90.0, 25.4)],
    "GRASS": [(60.0, 6.35), (120.0, 6.35)],
    "GRATE": [(0.0, 3.175), (90.0, 12.7)],
    "GRAVEL": [(15.0, 7.5), (75.0, 10.0), (135.0, 12.5)],
    "HEX": [(0.0, 9.525), (60.0, 9.525), (120.0, 9.525)],
    "HONEY": [(0.0, 6.35), (60.0, 6.35), (120.0, 6.35)],
    "HOUND": [(0.0, 6.35), (45.0, 6.35), (90.0, 12.7), (135.0, 12.7)],
    "INSUL": [(45.0, 9.525), (135.0, 9.525)],
    "MUDST": [(0.0, 9.525), (30.0, 19.05), (150.0, 19.05)],
    "PLAST": [(0.0, 6.35), (90.0, 19.05)],
    "SACNCR": [(0.0, 6.35), (45.0, 19.05), (135.0, 19.05)],
    "SQUARE": [(0.0, 6.35), (90.0, 6.35)],
    "STARS": [(0.0, 12.7), (60.0, 12.7), (120.0, 12.7)],
    "STEEL": [(0.0, 3.175), (90.0, 25.4)],
    "SWAMP": [(0.0, 6.35), (90.0, 25.4)],
    "TRIANG": [(0.0, 9.525), (60.0, 9.525), (120.0, 9.525)],
    "ZIGZAG": [(45.0, 6.35), (135.0, 6.35)],
}

# Prefer the canonical AutoCAD-compatible pattern definitions bundled with ezdxf.
# Pattern line record: (angle_deg, base_xy_mm, offset_xy_mm, dash_sequence_mm).
try:
    from ezdxf.tools.pattern import IMPERIAL_PATTERN as _ACAD_PAT
    for _name,_lines in _ACAD_PAT.items():
        HATCH_PATTERNS[_name.upper()] = [
            (float(a), (float(base[0])*25.4,float(base[1])*25.4),
             (float(off[0])*25.4,float(off[1])*25.4), [float(x)*25.4 for x in dash])
            for a,base,off,dash in _lines
        ]
except Exception:
    pass

_FONT_CANDIDATES = ["Noto Sans CJK TC", "Noto Sans TC", "Microsoft JhengHei", "PingFang TC", "Heiti TC",
                    "WenQuanYi Micro Hei", "Arial", "DejaVu Sans"]
_font_family = None
_cap_ratio = 0.72


def font_family():
    global _font_family, _cap_ratio
    if _font_family is None:
        fams = set(QFontDatabase.families())
        _font_family = next((f for f in _FONT_CANDIDATES if f in fams), QFont().family())
        f = QFont(_font_family)
        f.setPixelSize(200)
        cap = QFontMetricsF(f).capHeight()
        if cap > 20:
            _cap_ratio = cap / 200.0
    return _font_family


class View:
    """世界座標 <-> 裝置座標，以及 AutoCAD 風格標準 3D 視角。

    2D 圖元仍位於 Z=0 工作平面；SE/SW/NE/NW Isometric 會以正交投影顯示該工作平面，
    Solid3D 則使用完整 XYZ 投影。這使舊 2D 檔案完全相容，同時可逐步加入真正 3D 圖元。
    """

    def __init__(self, scale=1.0, ox=0.0, oy=0.0, w=100, h=100):
        self.scale, self.ox, self.oy, self.w, self.h = scale, ox, oy, w, h
        self.orientation = "TOP"
        self.azimuth = -45.0
        self.elevation = 35.264389682754654

    def _basis3(self):
        o = self.orientation.upper()
        if o == "TOP":
            return (1.0, 0.0), (0.0, -1.0), (0.0, 0.0)
        if o == "BOTTOM":
            return (1.0, 0.0), (0.0, 1.0), (0.0, 0.0)
        if o == "FRONT":
            return (1.0, 0.0), (0.0, 0.0), (0.0, -1.0)
        if o == "BACK":
            return (-1.0, 0.0), (0.0, 0.0), (0.0, -1.0)
        if o == "RIGHT":
            return (0.0, 0.0), (1.0, 0.0), (0.0, -1.0)
        if o == "LEFT":
            return (0.0, 0.0), (-1.0, 0.0), (0.0, -1.0)
        # 正交等角／自由軌道投影。名稱表示觀看者位於模型的哪個方位。
        if o == "CUSTOM":
            az, el = self.azimuth, self.elevation
        else:
            az = {"SEISO": -45.0, "SWISO": -135.0, "NEISO": 45.0, "NWISO": 135.0}.get(o, -45.0)
            el = 35.264389682754654
        a = math.radians(az)
        elev = math.radians(el)
        # screen horizontal = camera-right；screen vertical 向下，故使用 viewing-up 的反號。
        # Orthographic camera basis.  Each tuple is the screen projection of one
        # world axis (X/Y/Z).  At the canonical isometric elevation all three
        # projected axes therefore have the same length sqrt(2/3), as in AutoCAD.
        bx = (-math.sin(a), math.cos(a) * math.sin(elev))
        by = ( math.cos(a), math.sin(a) * math.sin(elev))
        bz = (0.0, -math.cos(elev))
        return bx, by, bz

    def set_orientation(self, name):
        self.orientation = str(name).upper()
        preset = {"SEISO": -45.0, "SWISO": -135.0, "NEISO": 45.0, "NWISO": 135.0}
        if self.orientation in preset:
            self.azimuth = preset[self.orientation]
            self.elevation = 35.264389682754654

    def set_angles(self, azimuth, elevation):
        self.azimuth = float(azimuth) % 360.0
        if self.azimuth > 180.0:
            self.azimuth -= 360.0
        self.elevation = max(-89.0, min(89.0, float(elevation)))
        self.orientation = "CUSTOM"

    def camera_forward(self):
        o=self.orientation.upper()
        # Direction from model toward camera; painter depth uses projection onto it.
        fixed={
            "TOP":(0.0,0.0,1.0), "BOTTOM":(0.0,0.0,-1.0),
            "FRONT":(0.0,-1.0,0.0), "BACK":(0.0,1.0,0.0),
            "RIGHT":(1.0,0.0,0.0), "LEFT":(-1.0,0.0,0.0),
        }
        if o in fixed:return fixed[o]
        a=math.radians(self.azimuth if o=="CUSTOM" else {"SEISO":-45.0,"SWISO":-135.0,"NEISO":45.0,"NWISO":135.0}.get(o,-45.0))
        e=math.radians(self.elevation if o=="CUSTOM" else 35.264389682754654)
        return (math.cos(a)*math.cos(e), math.sin(a)*math.cos(e), math.sin(e))

    def depth3(self, x, y, z=0.0):
        f=self.camera_forward()
        return x*f[0]+y*f[1]+z*f[2]

    def raw3(self, x, y, z=0.0):
        bx, by, bz = self._basis3()
        return (x*bx[0] + y*by[0] + z*bz[0], x*bx[1] + y*by[1] + z*bz[1])

    def project3(self, x, y, z=0.0):
        u, v = self.raw3(x, y, z)
        return QPointF(self.ox + u*self.scale, self.oy + v*self.scale)

    def w2s(self, x, y):
        return self.project3(x, y, 0.0)

    def transform(self):
        bx, by, _ = self._basis3()
        return QTransform(self.scale*bx[0], self.scale*bx[1],
                          self.scale*by[0], self.scale*by[1], self.ox, self.oy)

    def s2w(self, sx, sy):
        inv, ok = self.transform().inverted()
        if not ok:
            return (0.0, 0.0)
        q = inv.map(QPointF(sx, sy))
        return (q.x(), q.y())

    def screen_ray(self, sx, sy):
        """Orthographic world-space ray through a device point."""
        bx,by,bz=self._basis3();r=(bx[0],by[0],bz[0]);d=(bx[1],by[1],bz[1]);f=self.camera_forward()
        u=(float(sx)-self.ox)/max(self.scale,1e-12);v=(float(sy)-self.oy)/max(self.scale,1e-12)
        q0=(u*r[0]+v*d[0],u*r[1]+v*d[1],u*r[2]+v*d[2])
        return q0,f

    def screen_to_plane3(self, sx, sy, plane=None):
        """Map a device point to a principal 3D work plane for orthographic CAD input.

        The old s2w() can only invert the world XY plane and is singular in FRONT/RIGHT
        views.  This routine chooses XZ/YZ for those views (or an explicit plane), so
        existing 3D commands remain usable from every standard viewport.
        """
        o=self.orientation.upper()
        requested="" if plane is None else str(plane).upper()
        if requested=="VIEW":
            # The orthographic screen ray starts on the camera/view plane through
            # world origin, so it is the exact inverse for a View UCS.
            return self.screen_ray(sx,sy)[0]
        if plane is None:
            plane = "XZ" if o in ("FRONT","BACK") else ("YZ" if o in ("LEFT","RIGHT") else "XY")
        elif requested=="WCS":
            plane="XY"
        plane=str(plane).upper()
        bx,by,bz=self._basis3(); axes={"XY":(bx,by),"XZ":(bx,bz),"YZ":(by,bz)}
        a,b=axes.get(plane,(bx,by))
        u=(float(sx)-self.ox)/max(self.scale,1e-12);v=(float(sy)-self.oy)/max(self.scale,1e-12)
        det=a[0]*b[1]-a[1]*b[0]
        if abs(det)<1e-12:
            # Fall back to the plane naturally facing the current standard view.
            alt="XZ" if o in ("FRONT","BACK") else ("YZ" if o in ("LEFT","RIGHT") else "XY")
            a,b=axes[alt];plane=alt;det=a[0]*b[1]-a[1]*b[0]
        if abs(det)<1e-12:return (0.0,0.0,0.0)
        q1=(u*b[1]-v*b[0])/det;q2=(a[0]*v-a[1]*u)/det
        if plane=="XZ":return (q1,0.0,q2)
        if plane=="YZ":return (0.0,q1,q2)
        return (q1,q2,0.0)

    def world_rect(self):
        # world_rect is a 2D culling aid; when XY is edge-on use the natural work
        # plane projection rather than returning four (0,0) points.
        pts = [self.s2w(0,0), self.s2w(self.w,0), self.s2w(0,self.h), self.s2w(self.w,self.h)]
        if max(G.dist(pts[0],q) for q in pts[1:]) < 1e-9 and self.orientation in ("FRONT","BACK","LEFT","RIGHT"):
            q3=[self.screen_to_plane3(x,y) for x,y in ((0,0),(self.w,0),(0,self.h),(self.w,self.h))]
            if self.orientation in ("FRONT","BACK"):pts=[(q[0],q[2]) for q in q3]
            else:pts=[(q[1],q[2]) for q in q3]
        xs=[q[0] for q in pts]; ys=[q[1] for q in pts]
        return (min(xs), min(ys), max(xs), max(ys))


def entity_path(e):
    """圖元在世界座標下的 QPainterPath（快取在圖元上）。"""
    c = e.__dict__.get("_path")
    if c is not None:
        return c
    path = QPainterPath()
    if isinstance(e, Line):
        path.moveTo(e.x1, e.y1)
        path.lineTo(e.x2, e.y2)
    elif isinstance(e, Circle):
        path.addEllipse(QPointF(e.cx, e.cy), e.r, e.r)
    elif isinstance(e, Arc):
        rect = QRectF(e.cx - e.r, e.cy - e.r, 2 * e.r, 2 * e.r)
        path.arcMoveTo(rect, -e.a0)
        path.arcTo(rect, -e.a0, -e.span())
    elif isinstance(e, Polyline):
        first = True
        for pr in e.prims():
            s = G.prim_start(pr)
            if first:
                path.moveTo(s[0], s[1])
                first = False
            if pr[0] == 'L':
                path.lineTo(pr[3], pr[4])
            else:
                _, cx, cy, r, a0, span = pr[:6]
                rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
                if len(pr) < 7 or pr[6]:
                    path.arcTo(rect, -a0, -span)
                else:
                    path.arcTo(rect, -(a0 + span), span)
        if e.closed and not first:
            path.closeSubpath()
    elif isinstance(e, (Ellipse, Spline)):
        pts = e.points()
        if pts:
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
    elif isinstance(e, Hatch):
        path.setFillRule(Qt.FillRule.OddEvenFill)
        if getattr(e,"loop_prims",None):
            for lp in e.loop_prims:
                if not lp:continue
                st=G.prim_start(tuple(lp[0]));path.moveTo(st[0],st[1])
                for pr0 in lp:
                    pr=tuple(pr0)
                    if pr[0]=='L':path.lineTo(pr[3],pr[4])
                    elif pr[0]=='A':
                        _,cx,cy,r,a0,span,*rest=pr;rect=QRectF(cx-r,cy-r,2*r,2*r)
                        ccw=(len(pr)<7 or bool(pr[6]));path.arcTo(rect,-a0,-span if ccw else span)
                path.closeSubpath()
        else:
            for lp in e.loops:
                if len(lp) >= 3:
                    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in lp]))
                    path.closeSubpath()
    e.__dict__["_path"] = path
    return path


class Renderer:
    def __init__(self, doc):
        self.doc = doc
        self.dark = True          # 深色背景：顏色 7 畫成白色
        self.mono = False         # 單色出圖
        self.show_lw = False
        self.px_per_mm = None     # 出圖時設定，線粗用實際尺寸
        self.min_pen = 1.0
        self.visual_style = "2DWIREFRAME"
        self.interactive = False  # Orbit/gizmo drag use a lower display budget for stability.

    # ---- 畫筆
    def qcolor(self, aci):
        if self.mono:
            return QColor(0, 0, 0)
        if aci == 7:
            return QColor(255, 255, 255) if self.dark else QColor(0, 0, 0)
        r, g, b = aci_rgb(aci)
        if not self.dark and r > 235 and g > 235 and b > 235:
            return QColor(0, 0, 0)
        return QColor(r, g, b)

    def pen_width(self, e):
        lw = self.doc.lw_of(e)
        if self.px_per_mm:
            return max(self.min_pen, lw / 100.0 * self.px_per_mm)
        if self.show_lw:
            return max(1.0, round(lw / 100.0 * 4.0))
        return 1.0

    def entity_color(self, e):
        rgb=self.doc.rgb_of(e) if hasattr(self.doc,"rgb_of") else None
        if rgb is not None:
            col=QColor(*rgb)
            if not self.dark and col.red()>235 and col.green()>235 and col.blue()>235:
                col=QColor(0,0,0)
            return col
        return self.qcolor(self.doc.color_of(e))

    def pen_for(self, e, view, fade=False):
        col = self.entity_color(e)
        if fade:
            col.setAlpha(110)
        w = self.pen_width(e)
        pen = QPen(col, w)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pat = self.doc.pattern(self.doc.ltype_of(e))
        if pat:
            k = self.doc.vars.get("LTSCALE", 1.0) * e.lts * view.scale / w
            total = sum(abs(x) for x in pat) * k * w
            if 6.0 <= total <= 4000.0:
                d = [max(abs(x) * k, 1.0 / w) for x in pat]
                if len(d) % 2:
                    d.append(d[-1])
                pen.setDashPattern(d)
        return pen

    # ---- 主要繪製
    def paint(self, p, view, entities=None, cull=True):
        doc = self.doc
        wr = view.world_rect()
        texts = []
        solids = []
        p.setWorldTransform(view.transform())
        p.setBrush(Qt.BrushStyle.NoBrush)
        for e in (doc.entities if entities is None else entities):
            ly = doc.layer(e.layer)
            if not ly.on or ly.frozen:
                continue
            if self.px_per_mm and not ly.plot:
                continue
            if cull:
                # A Solid3D bbox is stored in world XY for legacy 2D compatibility.
                # Using that box to cull FRONT/RIGHT/isometric views can discard a solid
                # whose visible extent comes from Z.  Keep fast XY culling for TOP/2D,
                # but never reject a 3D solid from a non-TOP view with a 2D bbox.
                if not (isinstance(e, Solid3D) and view.orientation != "TOP"):
                    b = doc.bbox(e)
                    if b is not None and (b[2] < wr[0] or b[0] > wr[2] or b[3] < wr[1] or b[1] > wr[3]):
                        continue
            fade = ly.locked and not self.px_per_mm
            for leaf in doc.expand(e):
                if leaf is not e and not doc.visible(leaf):
                    continue
                if isinstance(leaf, (Text, MText)):
                    texts.append((leaf, fade))
                elif isinstance(leaf, Solid3D) and str(getattr(self, "visual_style", "")).upper() in ("SHADED", "SHADED_EDGES", "CONCEPTUAL"):
                    solids.append((leaf, self.pen_for(leaf, view, fade)))
                else:
                    self._draw_leaf(p, leaf, view, self.pen_for(leaf, view, fade), wr)
        # Shaded solids are depth-sorted together, not one object at a time.  This fixes
        # a farther solid incorrectly painting over a nearer solid.
        if solids:
            p.setWorldTransform(QTransform())
            self._draw_solids_global(p, solids, view)
        p.setWorldTransform(QTransform())
        for leaf, fade in texts:
            col = self.entity_color(leaf)
            if fade:
                col.setAlpha(110)
            self.draw_text(p, leaf, view, col)

    def _display_mesh(self, solid, face_limit=50000):
        """Return a bounded, finite mesh for interactive painting.

        Imported STEP/STL can be far denser than a QPainter viewport needs.  Solid3D
        keeps the authoritative geometry; this path only asks for a temporary LOD.
        """
        try:
            return solid.display_mesh(face_limit)
        except Exception:
            # Last-resort defensive path: never let a malformed external mesh kill paintEvent.
            vv=[]; mp={}
            for i,v in enumerate(getattr(solid,"vertices",[]) or []):
                try:x,y,z=map(float,v[:3])
                except Exception:continue
                if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):continue
                mp[i]=len(vv);vv.append((x,y,z))
            ff=[]
            for f in getattr(solid,"faces",[]) or []:
                try:ids=[mp[int(i)] for i in f if int(i) in mp]
                except Exception:continue
                if len(ids)>=3:
                    for k in range(1,len(ids)-1):
                        t=(ids[0],ids[k],ids[k+1])
                        if len(set(t))==3:ff.append(t)
                        if len(ff)>=face_limit:break
                if len(ff)>=face_limit:break
            ee=[];seen=set()
            for a,b,c in ff:
                for u,v in ((a,b),(b,c),(c,a)):
                    k=(u,v) if u<v else (v,u)
                    if k not in seen:seen.add(k);ee.append(k)
                    if len(ee)>=10000:break
                if len(ee)>=10000:break
            return vv,ff,ee

    def _mesh_topology(self, solid, verts, faces):
        """Cache triangle normals and edge adjacency for clean CAD-style edges.

        STL is a triangle mesh, but drawing every triangle edge makes a smooth model
        look "exploded".  Feature/silhouette extraction keeps the mesh authoritative
        while presenting only boundaries, sharp creases and the current-view outline.
        """
        key=(id(verts),id(faces),len(verts),len(faces))
        cached=solid.__dict__.get("_display_topology_cache")
        if cached and cached[0]==key:return cached[1]
        normals=[];edges={}
        for fi,f in enumerate(faces):
            if len(f)<3:
                normals.append((0.0,0.0,0.0));continue
            try:a,b,c=(verts[int(f[i])] for i in range(3))
            except Exception:
                normals.append((0.0,0.0,0.0));continue
            ux,uy,uz=b[0]-a[0],b[1]-a[1],b[2]-a[2];vx,vy,vz=c[0]-a[0],c[1]-a[1],c[2]-a[2]
            nx,ny,nz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx
            L=(nx*nx+ny*ny+nz*nz)**0.5
            n=(0.0,0.0,0.0) if L<1e-15 else (nx/L,ny/L,nz/L)
            normals.append(n)
            ids=[int(x) for x in f[:3]]
            for u,v in ((ids[0],ids[1]),(ids[1],ids[2]),(ids[2],ids[0])):
                if not (0<=u<len(verts) and 0<=v<len(verts)):continue
                ek=(u,v) if u<v else (v,u)
                arr=edges.setdefault(ek,[])
                if len(arr)<4:arr.append(fi)
        data=(normals,edges);solid.__dict__["_display_topology_cache"]=(key,data);return data

    def _feature_edges(self, solid, verts, faces, view, cap=6500, crease_deg=34.0, silhouette=True):
        normals,adj=self._mesh_topology(solid,verts,faces)
        fwd=view.camera_forward();ct=math.cos(math.radians(float(crease_deg)))
        out=[]
        for e,fl in adj.items():
            keep=False
            if len(fl)!=2:
                # Open boundary edges remain visible.
                keep=True
            else:
                n0,n1=normals[fl[0]],normals[fl[1]]
                a=n0[0]*fwd[0]+n0[1]*fwd[1]+n0[2]*fwd[2]
                b=n1[0]*fwd[0]+n1[1]*fwd[1]+n1[2]*fwd[2]
                d=n0[0]*n1[0]+n0[1]*n1[1]+n0[2]*n1[2]
                # Never draw a crease for which both adjacent faces point away from
                # the camera: that was the source of "back-side lines through solids".
                if d<ct and (a>-1e-5 or b>-1e-5):keep=True
                elif silhouette:
                    if (a>1e-5 and b<-1e-5) or (b>1e-5 and a<-1e-5):keep=True
            if keep:out.append(e)
        if len(out)>cap:
            step=max(1,len(out)//cap);out=out[::step][:cap]
        return out

    def _mesh_orientation_sign(self, solid, verts, faces):
        key=(len(verts),len(faces))
        cached=solid.__dict__.get("_orientation_cache")
        if cached and cached[0]==key:return cached[1]
        vol=0.0
        for f in faces[:120000]:
            if len(f)<3:continue
            a,b,c=(verts[f[i]] for i in range(3))
            vol += (a[0]*(b[1]*c[2]-b[2]*c[1]) - a[1]*(b[0]*c[2]-b[2]*c[0]) + a[2]*(b[0]*c[1]-b[1]*c[0]))
        sign=0 if abs(vol)<1e-10 else (1 if vol>0 else -1)
        solid.__dict__["_orientation_cache"]=(key,sign)
        return sign

    def _draw_solids_global(self, p, solids, view):
        style=str(getattr(self,"visual_style","SHADED_EDGES")).upper()
        # One global budget keeps assemblies responsive: ten 50k-face parts must not
        # become half a million QPainter polygons on every mouse move.
        total_budget=8000 if getattr(self,"interactive",False) else 26000
        per=max(2500,min(22000,total_budget//max(1,len(solids))))
        faces=[]; meshdata={}
        fwd=view.camera_forward()
        for solid,pen in solids:
            vv,ff,ee=self._display_mesh(solid,per); meshdata[id(solid)]=(vv,ff,ee)
            orient=self._mesh_orientation_sign(solid,vv,ff)
            for idx0 in ff:
                idx=[int(i) for i in idx0 if 0<=int(i)<len(vv)]
                if len(idx)!=3:continue
                a,b,c=(vv[idx[i]] for i in range(3))
                ux,uy,uz=b[0]-a[0],b[1]-a[1],b[2]-a[2]; vx,vy,vz=c[0]-a[0],c[1]-a[1],c[2]-a[2]
                nx,ny,nz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx
                n2=nx*nx+ny*ny+nz*nz
                if n2<1e-24 or not math.isfinite(n2):continue
                dot=nx*fwd[0]+ny*fwd[1]+nz*fwd[2]
                # Closed/oriented meshes can safely cull back faces, greatly reducing
                # painter-order artifacts.  Open/unknown meshes remain two-sided.
                if orient and dot*orient < -1e-12:continue
                dep=(view.depth3(*a)+view.depth3(*b)+view.depth3(*c))/3.0
                if math.isfinite(dep):faces.append((dep,solid,idx,pen,(nx,ny,nz),dot))
        faces.sort(key=lambda q:q[0])
        aa=p.testRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.Antialiasing,False)
        for _,solid,idx,pen,nrm,dot in faces:
            vv=meshdata[id(solid)][0]
            pts=[view.project3(*vv[i]) for i in idx]
            if any(not (math.isfinite(q.x()) and math.isfinite(q.y())) for q in pts):continue
            if any(max(abs(q.x()),abs(q.y()))>2e6 for q in pts):continue
            base=QColor(pen.color())
            if base.lightness()<80:base=QColor(145,155,168)
            nx,ny,nz=nrm; L=max((nx*nx+ny*ny+nz*nz)**0.5,1e-12);nx,ny,nz=nx/L,ny/L,nz/L
            # Stable RGB multiplication produces actual face shading instead of merely
            # changing HSL lightness. Closed solids are intentionally opaque so rear
            # triangles cannot bleed through a sphere/cylinder.
            lam=max(0.0,nx*0.35+ny*(-0.45)+nz*0.82)
            shade=0.52+0.48*lam
            fc=QColor(max(0,min(255,int(base.red()*shade))),max(0,min(255,int(base.green()*shade))),max(0,min(255,int(base.blue()*shade))),255)
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QBrush(fc));p.drawPolygon(QPolygonF(pts))
        p.setRenderHint(QPainter.RenderHint.Antialiasing,aa)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if style=="SHADED":return
        # CAD-style shaded edges: do not expose STL tessellation diagonals.  Keep only
        # real boundaries, sharp creases and the view-dependent silhouette.
        for solid,pen in solids:
            vv,ff,_ee=meshdata[id(solid)];p.setPen(pen)
            arr=self._feature_edges(solid,vv,ff,view,cap=5000 if not getattr(self,"interactive",False) else 2200)
            for ia,ib in arr:
                if 0<=ia<len(vv) and 0<=ib<len(vv):
                    a=view.project3(*vv[ia]);b=view.project3(*vv[ib])
                    if (math.isfinite(a.x()) and math.isfinite(a.y()) and math.isfinite(b.x()) and math.isfinite(b.y())
                            and max(abs(a.x()),abs(a.y()),abs(b.x()),abs(b.y()))<2e6):
                        p.drawLine(a,b)

    def draw_entity(self, p, e, view, pen, text_color=None):
        """用指定畫筆畫一個圖元（預覽、亮顯用）。呼叫前後 painter 都是裝置座標。"""
        wr = view.world_rect()
        p.setWorldTransform(view.transform())
        texts = []
        for leaf in self.doc.expand(e):
            if isinstance(leaf, (Text, MText)):
                texts.append(leaf)
            else:
                self._draw_leaf(p, leaf, view, pen, wr, override=True)
        p.setWorldTransform(QTransform())
        for leaf in texts:
            self.draw_text(p, leaf, view, text_color or pen.color())

    def _solid_wire_edges(self, e, style, view):
        """Return (display vertices, display edges) for existing wireframe styles.

        2D wireframe is intentionally CAD-clean: feature edges + silhouette.  3D
        wireframe is the explicit mesh view and therefore may show tessellation, but it
        still uses the bounded display mesh rather than the raw imported STL.
        """
        st=str(style).upper()
        limit=(9000 if getattr(self,"interactive",False) else 26000) if st=="3DWIREFRAME" else (7000 if getattr(self,"interactive",False) else 18000)
        vv,ff,ee=self._display_mesh(e,limit)
        if st=="3DWIREFRAME":
            cap=5000 if getattr(self,"interactive",False) else 11000
            arr=ee
            if len(arr)>cap:
                step=max(1,len(arr)//cap);arr=arr[::step][:cap]
            return vv,arr
        # Selection/highlight should describe the solid, not re-expose thousands of
        # tiny tessellation creases.  Imported STEP/STL uses a stricter crease angle
        # while preserving true boundaries and view silhouettes.
        imported=str(getattr(e,"shape","")).upper() in ("STEP","STL","OBJ","PLY","OFF","3MF","GLTF","GLB","DAE","AMF","VRML","WRL","MESH")
        return vv,self._feature_edges(e,vv,ff,view,cap=1800 if getattr(self,"interactive",False) else 4200,
                                      crease_deg=50.0 if imported else 34.0)

    def _draw_leaf(self, p, e, view, pen, wr, override=False):
        if isinstance(e, Solid3D):
            old=p.worldTransform();p.setWorldTransform(QTransform())
            style=str(getattr(self,"visual_style","2DWIREFRAME")).upper()
            # Normal document painting handles shaded solids globally.  This local path
            # is mainly used for selection/preview highlighting, so keep it bounded.
            vv,edges=self._solid_wire_edges(e,"3DWIREFRAME" if style=="3DWIREFRAME" else "2DWIREFRAME",view)
            p.setPen(pen)
            for a,b in edges:
                if 0<=a<len(vv) and 0<=b<len(vv):
                    pa=view.project3(*vv[a]);pb=view.project3(*vv[b])
                    if math.isfinite(pa.x()) and math.isfinite(pa.y()) and math.isfinite(pb.x()) and math.isfinite(pb.y()):p.drawLine(pa,pb)
            p.setWorldTransform(old);return
        if isinstance(e, Hatch):
            self._draw_hatch(p, e, view, pen, wr, override)
            return
        p.setPen(pen)
        if isinstance(e, XLine):
            seg = self._clip_xline(e, wr)
            if seg:
                p.drawLine(QPointF(seg[0], seg[1]), QPointF(seg[2], seg[3]))
            return
        if isinstance(e, Point):
            s = 1.5 / view.scale
            p.fillRect(QRectF(e.x - s, e.y - s, 2 * s, 2 * s), pen.color())
            return
        if isinstance(e, Polyline) and not override:
            # Preserve/display geometric LWPOLYLINE width.  Constant/uniform widths are
            # rendered in world units; varying widths are approximated segment-wise.
            widths=list(getattr(e,"widths",[]) or [])
            cw=abs(float(getattr(e,"const_width",0.0) or 0.0))
            if cw>1e-12 or any(max(abs(float(a)),abs(float(b)))>1e-12 for a,b in widths):
                prims=e.prims(); p.save()
                for i,pr in enumerate(prims):
                    if cw>1e-12:w=cw
                    elif widths:
                        a,b=widths[min(i,len(widths)-1)];w=max(abs(float(a)),abs(float(b)))
                    else:w=0.0
                    wp=QPen(pen.color(), max(w, 1.0/max(view.scale,1e-12)))
                    wp.setCosmetic(False);wp.setCapStyle(Qt.PenCapStyle.FlatCap);wp.setJoinStyle(Qt.PenJoinStyle.RoundJoin);p.setPen(wp)
                    if pr[0]=='L':p.drawLine(QPointF(pr[1],pr[2]),QPointF(pr[3],pr[4]))
                    else:
                        _,cx,cy,r,a0,span,*rest=pr; rect=QRectF(cx-r,cy-r,2*r,2*r);path=QPainterPath();path.arcMoveTo(rect,-a0);path.arcTo(rect,-a0,-span if len(pr)<7 or pr[6] else span);p.drawPath(path)
                p.restore();return
        p.drawPath(entity_path(e))

    def _clip_xline(self, e, wr):
        L = math.hypot(e.dx, e.dy)
        if L < G.EPS:
            return None
        ux, uy = e.dx / L, e.dy / L
        t0, t1 = (0.0 if e.ray else -1e30), 1e30
        for o, u, lo, hi in ((e.x, ux, wr[0], wr[2]), (e.y, uy, wr[1], wr[3])):
            if abs(u) < 1e-12:
                if o < lo or o > hi:
                    return None
                continue
            a, b = (lo - o) / u, (hi - o) / u
            if a > b:
                a, b = b, a
            t0, t1 = max(t0, a), min(t1, b)
        if t0 >= t1:
            return None
        return (e.x + ux * t0, e.y + uy * t0, e.x + ux * t1, e.y + uy * t1)

    def _draw_hatch(self, p, e, view, pen, wr, override):
        path = entity_path(e)
        col = QColor(pen.color())
        fams = HATCH_PATTERNS.get(e.pattern.upper())
        if fams is None:
            fams = HATCH_PATTERNS["ANSI31"]
        if override:
            col.setAlpha(60)
            p.fillPath(path, col)
            return
        if not fams:
            p.fillPath(path, col)
            return
        b = e.bbox()
        if b is None:
            return
        x0, y0, x1, y1 = max(b[0], wr[0]), max(b[1], wr[1]), min(b[2], wr[2]), min(b[3], wr[3])
        if x0 >= x1 or y0 >= y1:
            return
        lines = QPainterPath()
        count = 0
        for fam in fams:
            # legacy simplified tuple (angle, spacing) or canonical PAT tuple
            if len(fam)==2:
                a_deg,sp=fam;base=(0.0,0.0);off=None;dash=[]
                ar=math.radians(a_deg+e.angle);dx,dy=math.cos(ar),math.sin(ar);nx,ny=-dy,dx
                sdist=float(sp)*max(e.scale,1e-9);off=(nx*sdist,ny*sdist)
            else:
                a_deg,base,off,dash=fam
                ar=math.radians(float(a_deg)+e.angle);dx,dy=math.cos(ar),math.sin(ar)
                sc=max(e.scale,1e-9);ca,sa=math.cos(math.radians(e.angle)),math.sin(math.radians(e.angle))
                bx=(base[0]*ca-base[1]*sa)*sc;by=(base[0]*sa+base[1]*ca)*sc
                ox=(off[0]*ca-off[1]*sa)*sc;oy=(off[0]*sa+off[1]*ca)*sc
                base=(bx,by);off=(ox,oy);dash=[d*sc for d in dash]
            step=math.hypot(off[0],off[1])
            if step<1e-12:continue
            if step*view.scale<2.0:
                count=10**9;break
            # enumerate enough parallel pattern lines to cover the hatch bbox
            cs=((x0,y0),(x1,y0),(x1,y1),(x0,y1)); nx,ny=-dy,dx
            kvals=[(q[0]-base[0])*nx+(q[1]-base[1])*ny for q in cs]
            koff=off[0]*nx+off[1]*ny
            if abs(koff)<1e-12:koff=step
            k0=math.floor(min(kvals)/koff)-2;k1=math.ceil(max(kvals)/koff)+2
            if k0>k1:k0,k1=k1,k0
            count += k1-k0+1
            if count>4000:break
            for k in range(k0,k1+1):
                sx=base[0]+off[0]*k;sy=base[1]+off[1]*k
                ts=[(q[0]-sx)*dx+(q[1]-sy)*dy for q in cs];t0,t1=min(ts),max(ts)
                if not dash:
                    lines.moveTo(sx+dx*t0,sy+dy*t0);lines.lineTo(sx+dx*t1,sy+dy*t1);continue
                cyc=sum(abs(d) for d in dash)
                if cyc<1e-12:continue
                t=math.floor(t0/cyc)*cyc; idx=0
                while t<t1 and count<12000:
                    d=dash[idx%len(dash)];L=abs(d)
                    if abs(d)<1e-12:
                        qx,qy=sx+dx*t,sy+dy*t;rr=max(0.6/view.scale,0.02*max(e.scale,1.0));lines.addEllipse(QPointF(qx,qy),rr,rr);t+=max(0.8/view.scale,cyc*0.02)
                    elif d>0:
                        aa=max(t,t0);bb=min(t+L,t1)
                        if bb>aa:lines.moveTo(sx+dx*aa,sy+dy*aa);lines.lineTo(sx+dx*bb,sy+dy*bb)
                        t+=L
                    else:t+=L
                    idx+=1;count+=1
        if count > 4000:
            col.setAlpha(70)
            p.fillPath(path, col)
            return
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        hp = QPen(pen.color(), pen.widthF())
        hp.setCosmetic(True)
        p.setPen(hp)
        p.drawPath(lines)
        p.restore()

    # ---- 文字
    def draw_text(self, p, e, view, color):
        hpx = e.height * view.scale
        sp = view.w2s(e.x, e.y)
        if isinstance(e, MText):
            rows, wmax, total, col, top = e.layout()
        else:
            rows = None
        if hpx < 3.0:
            c = e.corners()
            p.setPen(QPen(color, 1))
            a, b = view.w2s(*c[0]), view.w2s(*c[1])
            if hpx >= 1.0:
                p.drawLine(a, b)
            else:
                p.drawPoint(a)
            return
        font = QFont(font_family())
        font.setPixelSize(max(1, int(round(hpx / _cap_ratio))))
        p.setFont(font)
        p.setPen(QPen(color))
        fm = QFontMetricsF(font)
        p.save()
        p.translate(sp)
        if e.rot:
            p.rotate(-e.rot)
        if rows is None:
            w = fm.horizontalAdvance(e.text)
            dy = {0: 0.0, 1: 0.0, 2: hpx / 2.0, 3: hpx}.get(e.valign, 0.0)
            p.drawText(QPointF(-w * e.halign / 2.0, dy), e.text)
        else:
            for dx, dyw, s in rows:
                w = fm.horizontalAdvance(s)
                p.drawText(QPointF({0: 0.0, 1: -w / 2.0, 2: -w}[col], -dyw * view.scale), s)
        p.restore()


# ---------------------------------------------------------------- 輸出
PAPER = {"A4": QPageSize.PageSizeId.A4, "A3": QPageSize.PageSizeId.A3, "A2": QPageSize.PageSizeId.A2,
         "A1": QPageSize.PageSizeId.A1, "A0": QPageSize.PageSizeId.A0}


def _fit_view(area, w, h, scale=None, margin=0.0):
    ww, wh = max(area[2] - area[0], 1e-9), max(area[3] - area[1], 1e-9)
    if scale is None:
        scale = min((w - 2 * margin) / ww, (h - 2 * margin) / wh)
    cx, cy = (area[0] + area[2]) / 2.0, (area[1] + area[3]) / 2.0
    return View(scale, w / 2.0 - cx * scale, h / 2.0 + cy * scale, w, h)


def plot(doc, p, pw, ph, ppm, area=None, mono=True, units_per_mm=None, lineweights=True):
    """把圖面畫到已開啟的 painter（PDF 或印表機）。ppm = 裝置每 mm 的像素數。"""
    area = area or doc.extents() or (0, 0, 100, 100)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    view = _fit_view(area, pw, ph, None if units_per_mm is None else ppm / units_per_mm)
    r = Renderer(doc)
    r.dark, r.mono, r.px_per_mm = False, mono, ppm
    r.min_pen = ppm * 0.13
    if not lineweights:
        r.pen_width = lambda e: ppm * 0.18
    p.setClipRect(QRectF(0, 0, pw, ph))
    r.paint(p, view, cull=False)


def export_pdf(doc, path, paper="A3", landscape=True, area=None, mono=True, units_per_mm=None, lineweights=True):
    """出圖到 PDF。units_per_mm=None 表示佈滿圖紙；否則為「1 mm 圖紙 = 幾個圖面單位」(比例 1:n)。"""
    w = QPdfWriter(path)
    w.setResolution(600)
    w.setPageSize(QPageSize(PAPER.get(paper, QPageSize.PageSizeId.A3)))
    w.setPageOrientation(QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait)
    w.setPageMargins(QMarginsF(7, 7, 7, 7), QPageLayout.Unit.Millimeter)
    p = QPainter(w)
    try:
        plot(doc, p, p.viewport().width(), p.viewport().height(), 600 / 25.4, area, mono, units_per_mm, lineweights)
    finally:
        p.end()


def export_svg(doc, path, mono=False):
    from PySide6.QtSvg import QSvgGenerator
    area = doc.extents() or (0, 0, 100, 100)
    ww, wh = max(area[2] - area[0], 1e-6), max(area[3] - area[1], 1e-6)
    k = 2000.0 / max(ww, wh)
    W, H = int(ww * k) + 40, int(wh * k) + 40
    g = QSvgGenerator()
    g.setFileName(path)
    g.setSize(QSize(W, H))
    g.setViewBox(QRectF(0, 0, W, H))
    g.setTitle("PyCAD 2D")
    p = QPainter(g)
    try:
        r = Renderer(doc)
        r.dark, r.mono = False, mono
        r.paint(p, _fit_view(area, W, H, margin=20), cull=False)
    finally:
        p.end()


def export_png(doc, path, width=3000, dark=False):
    area = doc.extents() or (0, 0, 100, 100)
    ww, wh = max(area[2] - area[0], 1e-6), max(area[3] - area[1], 1e-6)
    W = int(width)
    H = max(64, int(W * wh / ww))
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(QColor(33, 40, 48) if dark else QColor(255, 255, 255))
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = Renderer(doc)
        r.dark = dark
        r.min_pen = max(1.0, W / 2000.0)
        r.pen_width = lambda e: r.min_pen
        r.paint(p, _fit_view(area, W, H, margin=W * 0.03), cull=False)
    finally:
        p.end()
    img.save(path)
