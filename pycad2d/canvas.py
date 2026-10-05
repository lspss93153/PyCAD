# SPDX-License-Identifier: GPL-3.0-only
"""繪圖區：顯示、滑鼠鍵盤輸入、物件鎖點、選取、掣點，以及指令 generator 的驅動。"""
import html
import math
import traceback
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPolygonF, QPixmap, QFontMetricsF, QTransform
from PySide6.QtWidgets import QWidget, QMenu
from . import geometry as G
from . import commands as C
from .commands import Kw, Req
from .model import Document, Hatch, Text, MText, Dim, Insert, XLine, Point, Polyline, Solid3D, fmt
from .render import Renderer, View, font_family

SNAP_NAMES = {"END": "端點", "MID": "中點", "CEN": "中心點", "NOD": "節點", "QUA": "四分點", "INT": "交點",
              "INS": "插入點", "PER": "垂直點", "TAN": "切點", "NEA": "最近點", "GCE": "幾何中心"}
SNAP_ORDER = ["END", "MID", "CEN", "GCE", "NOD", "QUA", "INT", "INS", "PER", "TAN", "NEA"]
BG = QColor(33, 40, 48)
APERTURE = 10
PICKBOX = 4
GRIP = 4.5


class WorkPlane:
    """Single source of truth for 3D point input.

    ``origin`` is the geometric plane origin used for ray/plane intersection.
    ``coord_origin`` is the UCS/local-coordinate origin used by typed coordinates.
    Keeping the two separate is important: after the first point of a multi-point
    command the *geometric* plane must pass through that point, while absolute typed
    coordinates must keep the same UCS meaning.
    """
    __slots__=("origin","coord_origin","u","v","n")
    def __init__(self, origin, u, v, n, coord_origin=None):
        self.origin=tuple(float(x) for x in origin)
        self.coord_origin=tuple(float(x) for x in (origin if coord_origin is None else coord_origin))
        self.u=tuple(float(x) for x in u)
        self.v=tuple(float(x) for x in v)
        self.n=tuple(float(x) for x in n)
    def with_plane_origin(self, origin):
        return WorkPlane(origin,self.u,self.v,self.n,self.coord_origin)
    def to_world(self, q):
        u=float(q[0]) if len(q)>0 else 0.0; v=float(q[1]) if len(q)>1 else 0.0; w=float(q[2]) if len(q)>2 else 0.0
        o=self.coord_origin; a=self.u; b=self.v; n=self.n
        return (o[0]+u*a[0]+v*b[0]+w*n[0], o[1]+u*a[1]+v*b[1]+w*n[1], o[2]+u*a[2]+v*b[2]+w*n[2])
    def to_local(self, q):
        o=self.coord_origin
        d=(float(q[0])-o[0],float(q[1])-o[1],float(q[2] if len(q)>2 else 0.0)-o[2])
        return (sum(d[i]*self.u[i] for i in range(3)),sum(d[i]*self.v[i] for i in range(3)),sum(d[i]*self.n[i] for i in range(3)))


def _vnorm(a):
    L=math.sqrt(sum(float(x)*float(x) for x in a))
    return tuple(float(x)/L for x in a) if L>1e-12 else None

def _vcross(a,b):
    return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])

def _vdot(a,b):
    return sum(a[i]*b[i] for i in range(3))


class Settings:
    """跨圖面共用的製圖設定（狀態列上的那些開關）。"""

    def __init__(self):
        self.grid = True
        self.snap = False
        self.ortho = False
        self.polar = True
        self.osnap = True
        self.otrack = False
        self.dyn = True
        self.ducs = False
        self.lw = False
        self.modes = {"END", "MID", "CEN", "INT"}
        self.grid_size = 10.0
        self.snap_size = 10.0
        # 45° is the most useful general drafting default. TAB is reserved for
        # dynamic-input field switching (distance <-> angle), matching CAD convention.
        self.polar_inc = 45.0


class CadCanvas(QWidget):
    promptChanged = Signal(str)
    history = Signal(str)
    coordChanged = Signal(float, float, float)
    selectionChanged = Signal()
    docChanged = Signal()
    commandRequested = Signal(str)
    keyTyped = Signal(str)
    editRequested = Signal(object)

    def __init__(self, doc=None, settings=None, ui=None):
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setMinimumSize(200, 150)
        self.doc = doc or Document()
        self.s = settings or Settings()
        self.ui = ui
        self.renderer = Renderer(self.doc)
        self.view = View(2.0, 60.0, 400.0, 800, 600)
        self._first_show = True
        self._cache = None
        self.prev_views = []
        self._wheel_pixel_accum = 0.0

        self.selection = []
        self.pending = []           # 「選取物件」提示期間累積的選集
        self.previous_sel = []
        self.grip_selection = []
        self.gen = None
        self.req = None
        self.cmd_name = ""
        self._touched = False
        self._added = []
        self._preselect = None
        self.last_point = (0.0, 0.0)
        self.last_window = None

        self.mouse = QPointF(-100, -100)
        self.cur_pt = (0.0, 0.0)
        self.snap_hit = None        # (kind, (x, y))
        self.track = None           # (base, angle)
        self.otrack_points = []      # F11 物件鎖點追蹤的取得點
        self.temp_osnap = None       # Shift+右鍵：單次暫時鎖點模式
        self.entity_shift = False    # entity 點選當下是否按住 Shift（TRIM/EXTEND 切換）
        self.hover = None
        self.hover_grip = None      # (entity, index)
        self.box_start = None
        self.box_wait = False
        self.panning = False
        self.pan_last = None
        self.inside = False
        self.workspace_3d = False
        self.visual_style = "2DWIREFRAME"
        self.orbiting = False
        self.orbit_last = None
        self.orbit_once = False
        self.ucs_mode = "WCS"
        self.quad_view = False
        self._quad_zoom = {"TOP":1.0,"FRONT":1.0,"RIGHT":1.0,"SEISO":1.0}
        self.quad_active = "SEISO"
        self.last_subedge = None
        self.last_subface = None
        self._gizmo_drag = None
        self._plane_error_shown = False
        self._orbit_pivot = None
        self._input_plane_lock = None
        self._quick_polar_presets = (30.0, 45.0, 60.0, 90.0, 15.0)
        self._polar_sticky = None
        self._dyn_field = "DIST"

    # ================================================================ 文件操作（給指令用）
    def make(self, cls, **kw):
        return cls(**self.doc.new_props(), **kw)

    def touch(self):
        if not self._touched:
            self.doc.push_undo()
            self._touched = True

    def _fresh_for_add(self, e, reserved=None):
        """Give copied entities a new identity while preserving edited replacements.

        Geometry transforms intentionally preserve uid so relationships survive MOVE/
        ROTATE/SCALE.  A true COPY is distinguishable here because the old uid already
        exists in the document.
        """
        import uuid
        used={getattr(x,"uid",None) for x in self.doc.entities}
        if reserved:used.update(reserved)
        u=getattr(e,"uid",None)
        if not u or u in used:
            nu=uuid.uuid4().hex
            # Preserve caller references for normal transformed copies; only clone if
            # the exact same object is already owned by the document.
            if any(e is x for x in self.doc.entities):
                e=e.clone(uid=nu)
            else:
                e.uid=nu
        return e

    def _sync_hatches(self, uids):
        if self.doc.refresh_associative_hatches(uids):
            # Replace stale selection references with current objects of the same uid.
            sm={getattr(e,"uid",None):e for e in self.doc.entities}
            self.selection=[sm.get(getattr(e,"uid",None),e) for e in self.selection if getattr(e,"uid",None) in sm]

    def add(self, e):
        self.touch()
        e=self._fresh_for_add(e)
        self.doc.entities.append(e)
        self._added.append(e)
        self.doc.layer(e.layer)
        self.invalidate()
        return e

    def add_many(self, ents):
        self.touch()
        fresh=[];reserved=set()
        for e in ents:
            e=self._fresh_for_add(e,reserved);reserved.add(getattr(e,"uid",None));fresh.append(e)
        self.doc.entities.extend(fresh)
        self._added.extend(fresh)
        self.invalidate()
        return fresh

    def remove(self, ents):
        self.touch()
        ids = {id(e) for e in ents}; uids={getattr(e,"uid",None) for e in ents}
        self.doc.entities = [e for e in self.doc.entities if id(e) not in ids]
        self.selection = [e for e in self.selection if id(e) not in ids]
        self._sync_hatches(uids)
        self.invalidate()

    def replace(self, old, new):
        self.touch()
        new = new if isinstance(new, list) else [new]
        # One-for-one edits retain stable identity; split results keep it on the first
        # piece only, preventing duplicate relationship targets.
        if new:
            new=[new[0].clone(uid=getattr(old,"uid",new[0].uid))]+[self._fresh_for_add(x) for x in new[1:]]
        out = []
        for e in self.doc.entities:
            if e is old:
                out.extend(new)
            else:
                out.append(e)
        self.doc.entities = out
        self._sync_hatches({getattr(old,"uid",None)})
        self.invalidate()

    def replace_many(self, olds, news, exact=True):
        self.touch()
        changed={getattr(o,"uid",None) for o in olds}
        if exact and len(olds) == len(news):
            fixed=[n.clone(uid=getattr(o,"uid",n.uid)) for o,n in zip(olds,news)]
            mp = {id(o): n for o, n in zip(olds, fixed)}
            self.doc.entities = [mp.get(id(e), e) for e in self.doc.entities]
        else:
            ids = {id(e) for e in olds}; fresh=[];reserved=set()
            for n in news:
                n=self._fresh_for_add(n,reserved);reserved.add(getattr(n,"uid",None));fresh.append(n)
            self.doc.entities = [e for e in self.doc.entities if id(e) not in ids] + fresh
        self._sync_hatches(changed)
        self.invalidate()

    def undo_last_add(self):
        if self._added:
            self.remove([self._added.pop()])

    def msg(self, text):
        self.history.emit(text)

    def changed(self):
        self.invalidate()
        self.docChanged.emit()

    def regen(self):
        for e in self.doc.entities:
            for k in ("_path", "_prims", "_bbox", "_pts", "_parts", "_exp"):
                e.__dict__.pop(k, None)
        self.invalidate()

    def keep_selection(self, ents):
        self._keep = list(ents)

    def view_rect(self):
        return self.view.world_rect()

    # ================================================================ 視圖
    def invalidate(self):
        self._cache = None
        self.update()

    def _push_view(self):
        self.prev_views.append((self.view.scale, self.view.ox, self.view.oy, self.view.orientation, self.view.azimuth, self.view.elevation))
        del self.prev_views[:-30]

    def zoom_extents(self):
        self._push_view()
        b = self.doc.extents()
        if b is None:
            b = (0.0, 0.0, 420.0, 297.0)
        self._fit(b, 0.92)

    def _fit(self, b, k=1.0):
        w, h = max(self.width(), 50), max(self.height(), 50)
        # 以目前視角的投影範圍 fit；TOP 之外不再錯把 world bbox 當成 screen bbox。
        pts = [(b[0], b[1], 0.0), (b[2], b[1], 0.0), (b[2], b[3], 0.0), (b[0], b[3], 0.0)]
        if self.view.orientation != "TOP":
            for ent in self.doc.entities:
                if isinstance(ent, Solid3D):
                    pts.extend(ent.vertices)
        raw = [self.view.raw3(*q) for q in pts]
        xs = [q[0] for q in raw]; ys = [q[1] for q in raw]
        u0,u1,v0,v1 = min(xs),max(xs),min(ys),max(ys)
        ww, wh = max(u1-u0, 1e-9), max(v1-v0, 1e-9)
        sc = min(w / ww, h / wh) * k
        sc = max(1e-9, min(1e9, sc))
        self.view.scale = sc
        self.view.ox = w/2.0 - (u0+u1)/2.0*sc
        self.view.oy = h/2.0 - (v0+v1)/2.0*sc
        self.invalidate()

    def set_view_orientation(self, name, fit=True):
        name = str(name).upper()
        if name == self.view.orientation:
            return
        self._push_view()
        self.view.set_orientation(name)
        if fit:
            b = self.doc.extents() or (0.0, 0.0, 420.0, 297.0)
            self._fit(b, 0.88)
        else:
            self.invalidate()
        labels = {"TOP":"上視", "BOTTOM":"下視", "FRONT":"前視", "BACK":"後視",
                  "LEFT":"左視", "RIGHT":"右視", "SEISO":"東南等角", "SWISO":"西南等角",
                  "NEISO":"東北等角", "NWISO":"西北等角"}
        self.msg("視圖：%s" % labels.get(name, name))

    def zoom_rect(self, a, b):
        if abs(a[0] - b[0]) < G.EPS or abs(a[1] - b[1]) < G.EPS:
            return
        self._push_view()
        self._fit((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))

    def zoom_factor(self, f, at=None):
        """Cursor-centred zoom that works in every 3D projection.

        v0.6 used s2w() and then reconstructed ox/oy with TOP-view equations,
        causing the model to jump in isometric/front/right views.  Keep the
        projected (u,v) coordinate under the cursor instead.
        """
        if at is None:
            self._push_view()
            at = QPointF(self.width() / 2.0, self.height() / 2.0)
        old = max(self.view.scale, 1e-12)
        u = (at.x() - self.view.ox) / old
        v = (at.y() - self.view.oy) / old
        ns = max(1e-9, min(1e9, old * f))
        self.view.scale = ns
        self.view.ox = at.x() - u * ns
        self.view.oy = at.y() - v * ns
        self.invalidate()

    def set_workspace_3d(self, enabled):
        self.workspace_3d = bool(enabled)
        if not self.workspace_3d:
            self.visual_style = "2DWIREFRAME"
        self.renderer.visual_style = self.visual_style
        self._restore_cursor()
        self.invalidate()

    def set_visual_style(self, style):
        style = str(style).upper()
        if style not in ("2DWIREFRAME", "3DWIREFRAME", "SHADED_EDGES", "CONCEPTUAL"):
            style = "3DWIREFRAME"
        self.visual_style = style
        self.renderer.visual_style = style
        names = {"2DWIREFRAME":"2D 線架構", "3DWIREFRAME":"3D 線架構",
                 "SHADED_EDGES":"著色含邊線", "CONCEPTUAL":"概念"}
        self.msg("視覺型式：" + names.get(style, style))
        self.invalidate()

    def _restore_cursor(self):
        """Restore the normal drafting cursor after pan/orbit/gizmo operations.

        2D keeps the long software crosshair (therefore the native cursor stays hidden).
        In 3D we keep a native cross cursor as a safety fallback: point requests carry XYZ
        coordinates, and a paint/preview failure must never leave the user with no visible
        pointer at all.
        """
        self.setCursor(Qt.CursorShape.CrossCursor if self.workspace_3d else Qt.CursorShape.BlankCursor)

    @staticmethod
    def _project_point(view, q):
        """Project either a 2D or XYZ command point to device coordinates."""
        if isinstance(q, tuple) and len(q) >= 3:
            return view.project3(float(q[0]), float(q[1]), float(q[2]))
        return view.w2s(float(q[0]), float(q[1]))

    def start_orbit(self):
        self.orbit_once = True
        self.msg("3DORBIT：按住左鍵拖曳旋轉視圖；Esc 取消。也可隨時使用 Shift+滑鼠中鍵。")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def _orbit_pivot_point(self):
        solids=[e for e in self.selection if isinstance(e,Solid3D) and e.bbox3d()]
        if not solids: solids=[e for e in self.doc.entities if isinstance(e,Solid3D) and e.bbox3d()]
        if solids:
            bs=[e.bbox3d() for e in solids]
            return ((min(b[0] for b in bs)+max(b[3] for b in bs))*0.5,
                    (min(b[1] for b in bs)+max(b[4] for b in bs))*0.5,
                    (min(b[2] for b in bs)+max(b[5] for b in bs))*0.5)
        b=self.doc.extents()
        return ((b[0]+b[2])*0.5,(b[1]+b[3])*0.5,0.0) if b else (0.0,0.0,0.0)

    def _orbit_by(self, dx, dy):
        # Keep one pivot for the entire drag.  Compensating ox/oy after rotation keeps
        # the pivot at the same screen pixel instead of letting the model drift.
        pivot=self._orbit_pivot or self._orbit_pivot_point(); before=self.view.project3(*pivot)
        if self.view.orientation != "CUSTOM":
            presets = {"SEISO":(-45.0,35.2644), "SWISO":(-135.0,35.2644),
                       "NEISO":(45.0,35.2644), "NWISO":(135.0,35.2644),
                       "TOP":(-90.0,89.0), "BOTTOM":(-90.0,-89.0),
                       "FRONT":(-90.0,0.0), "BACK":(90.0,0.0),
                       "RIGHT":(0.0,0.0), "LEFT":(180.0,0.0)}
            az, el = presets.get(self.view.orientation, (-45.0, 35.2644))
        else:
            az, el = self.view.azimuth, self.view.elevation
        self.view.set_angles(az + dx * 0.35, el - dy * 0.35)
        after=self.view.project3(*pivot); self.view.ox += before.x()-after.x(); self.view.oy += before.y()-after.y()
        self.invalidate()

    def set_ucs_mode(self, mode):
        self.ucs_mode = str(mode).upper()
        self.msg("UCS：" + self.ucs_mode)
        self.invalidate()

    def toggle_dynamic_ucs(self):
        self.s.ducs = not bool(getattr(self.s, "ducs", False))
        self.msg("動態 UCS (F6)：" + ("打開" if self.s.ducs else "關閉"))
        if self.ui is not None and hasattr(self.ui, "sync_toggles"):
            self.ui.sync_toggles()
        self.invalidate()

    def toggle_quad_view(self):
        if not self.workspace_3d:
            self.msg("四視埠僅在 3D 建模工作區顯示。")
            return
        self.quad_view = not self.quad_view
        self.msg("視埠：" + ("四視埠（上/前/右/東南等角）" if self.quad_view else "單一視埠"))
        self.invalidate()

    def _quad_views(self):
        """Build four AutoCAD-style engineering views fitted to the current model."""
        rects=[QRectF(0,0,self.width()/2,self.height()/2), QRectF(self.width()/2,0,self.width()/2,self.height()/2),
               QRectF(0,self.height()/2,self.width()/2,self.height()/2), QRectF(self.width()/2,self.height()/2,self.width()/2,self.height()/2)]
        names=["TOP","FRONT","RIGHT","SEISO"]
        b=self.doc.extents() or (0.0,0.0,100.0,100.0)
        pts=[(b[0],b[1],0.0),(b[2],b[1],0.0),(b[2],b[3],0.0),(b[0],b[3],0.0)]
        for e in self.doc.entities:
            if isinstance(e,Solid3D): pts.extend(e.vertices)
        out=[]
        for r,name in zip(rects,names):
            q=View(1.0,0.0,0.0,int(r.width()),int(r.height())); q.set_orientation(name)
            raw=[q.raw3(*p) for p in pts]; xs=[a[0] for a in raw]; ys=[a[1] for a in raw]
            ww=max(max(xs)-min(xs),1e-9); hh=max(max(ys)-min(ys),1e-9)
            q.scale=min((r.width()-24)/ww,(r.height()-36)/hh)*0.9*float(self._quad_zoom.get(name,1.0))
            q.ox=r.left()+r.width()/2-(min(xs)+max(xs))/2*q.scale
            q.oy=r.top()+r.height()/2-(min(ys)+max(ys))/2*q.scale
            q.w=self.width(); q.h=self.height(); out.append((r,name,q))
        return out

    def _view_at(self, pos):
        """Return (view, viewport_name, rect) for the device point."""
        if self.quad_view and self.workspace_3d:
            for r,name,qv in self._quad_views():
                if r.contains(QPointF(pos)):
                    self.quad_active=name
                    return qv,name,r
        return self.view,self.view.orientation,QRectF(0,0,self.width(),self.height())

    def work_plane(self, view=None):
        """Return the active immutable work plane for all 3D input.

        Once a multi-point 3D operation has acquired its first reference, the plane
        is frozen until that operation finishes.  DUCS may propose the initial plane
        but cannot silently retarget halfway through a drag.
        """
        view=view or self.view
        if self._input_plane_lock is not None and self._uses_3d_input():
            return self._input_plane_lock
        cam=view.camera_forward()
        # Dynamic UCS uses the currently acquired face, but still obeys the normal
        # convention: positive local W points toward the user.
        if ((getattr(self.s,"ducs",False) or bool(getattr(self.req,"face_pick",False))) and self.last_subface is not None):
            solid,face=self.last_subface
            ids=[int(i) for i in face if 0<=int(i)<len(solid.vertices)]
            if len(ids)>=3:
                a=solid.vertices[ids[0]]; b=solid.vertices[ids[1]]; c=solid.vertices[ids[2]]
                u=_vnorm((b[0]-a[0],b[1]-a[1],b[2]-a[2]))
                raw=_vcross((b[0]-a[0],b[1]-a[1],b[2]-a[2]),(c[0]-a[0],c[1]-a[1],c[2]-a[2]))
                n=_vnorm(raw)
                if u is not None and n is not None:
                    if _vdot(n,cam)<0:n=tuple(-x for x in n)
                    v=_vnorm(_vcross(n,u))
                    if v is not None:return WorkPlane(a,u,v,n)
        mode=str(self.ucs_mode or "WCS").upper()
        # WCS is always world XY.  It must never silently follow FRONT/RIGHT view.
        if mode=="WCS":
            u,v,n=(1,0,0),(0,1,0),(0,0,1)
        elif mode=="FRONT":
            u,v,n=(1,0,0),(0,0,1),(0,-1,0)
        elif mode=="RIGHT":
            u,v,n=(0,1,0),(0,0,1),(1,0,0)
        elif mode=="TOP":
            u,v,n=(1,0,0),(0,1,0),(0,0,1)
        elif mode=="VIEW":
            bx,by,bz=view._basis3()
            u=_vnorm((bx[0],by[0],bz[0])) or (1,0,0)
            # Device Y points down, so invert it to obtain a conventional local +V.
            v=_vnorm((-bx[1],-by[1],-bz[1])) or (0,1,0)
            n=_vnorm(_vcross(u,v)) or cam
        else:
            u,v,n=(1,0,0),(0,1,0),(0,0,1)
        if _vdot(n,cam)<0:
            # Normal orientation follows the camera, but U/V coordinate semantics do
            # not.  In particular WCS x/y must remain world X/Y in BOTTOM/BACK views.
            n=tuple(-x for x in n)
        return WorkPlane((0,0,0),u,v,n)

    def effective_work_plane(self, view=None):
        """Work plane used for interactive point acquisition.

        WCS itself remains world XY.  If that plane is edge-on in a side view and a
        true 3D primitive/edit command is asking for a point, use a temporary
        view-aligned plane instead of returning a singular point.  This is deliberately
        temporary and does not mutate the user's UCS mode.
        """
        view=view or self.view
        p=self.work_plane(view)
        if self._input_plane_lock is not None:
            return p
        den=abs(_vdot(p.n,view.camera_forward()))
        if den>=1e-7 or str(self.ucs_mode or "WCS").upper()!="WCS" or not self._uses_3d_input():
            return p
        bx,by,bz=view._basis3()
        u=_vnorm((bx[0],by[0],bz[0])) or (1.0,0.0,0.0)
        v=_vnorm((-bx[1],-by[1],-bz[1])) or (0.0,0.0,1.0)
        n=_vnorm(_vcross(u,v)) or view.camera_forward()
        if _vdot(n,view.camera_forward())<0:n=tuple(-x for x in n)
        return WorkPlane(p.origin,u,v,n,p.coord_origin)

    def face_frame3d(self):
        """Return the acquired face's stable (centre,U,V,outward-N) frame."""
        hit=self.last_subface
        if not hit:return None
        solid,face=hit
        if not isinstance(solid,Solid3D):return None
        ids=[int(i) for i in face if 0<=int(i)<len(solid.vertices)]
        if len(ids)<3:return None
        pts=[solid.vertices[i] for i in ids]
        cen=(sum(q[0] for q in pts)/len(pts),sum(q[1] for q in pts)/len(pts),sum(q[2] for q in pts)/len(pts))
        best=None
        for a,b in zip(pts,pts[1:]+pts[:1]):
            d=(b[0]-a[0],b[1]-a[1],b[2]-a[2]);ll=_vdot(d,d)
            if best is None or ll>best[0]:best=(ll,d)
        if best is None or best[0]<1e-24:return None
        u=_vnorm(best[1]);a,b,c=pts[0],pts[1],pts[2]
        n=_vnorm(_vcross((b[0]-a[0],b[1]-a[1],b[2]-a[2]),(c[0]-a[0],c[1]-a[1],c[2]-a[2])))
        if u is None or n is None:return None
        bb=solid.bbox3d()
        if bb:
            sc=((bb[0]+bb[3])*0.5,(bb[1]+bb[4])*0.5,(bb[2]+bb[5])*0.5)
            if _vdot(n,(cen[0]-sc[0],cen[1]-sc[1],cen[2]-sc[2]))<0:n=tuple(-x for x in n)
        # Make U truly tangent to the face and V right-handed with outward N.
        du=_vdot(u,n);u=_vnorm(tuple(u[i]-du*n[i] for i in range(3)))
        if u is None:return None
        v=_vnorm(_vcross(n,u))
        if v is None:return None
        return cen,u,v,n

    @staticmethod
    def ray_plane(view, pos, plane):
        q0,f=view.screen_ray(pos.x(),pos.y()); n=plane.n
        den=_vdot(n,f)
        if abs(den)<1e-9:return None
        t=_vdot(n,(plane.origin[0]-q0[0],plane.origin[1]-q0[1],plane.origin[2]-q0[2]))/den
        return (q0[0]+f[0]*t,q0[1]+f[1]*t,q0[2]+f[2]*t)

    def _uses_3d_input(self):
        return self.workspace_3d and self.cmd_name.upper() in {"BOX","CYLINDER","CONE","SPHERE","WEDGE","PYRAMID","TORUS","MOVE3D","PLACE3D","ROTATE3D","SCALE3D","COPY","PASTECLIP"}

    def _screen_point(self, view, pos):
        if self._uses_3d_input():
            q=self.ray_plane(view,pos,self.effective_work_plane(view))
            if q is None:
                if not self._plane_error_shown:
                    self.msg("目前工作平面與視線平行，無法取得點。請切換視圖或使用鍵盤座標。")
                    self._plane_error_shown=True
                return None
            self._plane_error_shown=False
            return q
        return view.s2w(pos.x(),pos.y())

    @staticmethod
    def _axis_world(axis):
        return {"X":(1.0,0.0,0.0),"Y":(0.0,1.0,0.0),"Z":(0.0,0.0,1.0)}[axis]

    @staticmethod
    def _point_in_poly2(pos, poly):
        # Small convex gizmo handles; winding-independent crossing test.
        x,y=pos.x(),pos.y(); inside=False
        pts=[(q.x(),q.y()) for q in poly]
        j=len(pts)-1
        for i,(xi,yi) in enumerate(pts):
            xj,yj=pts[j]
            if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/((yj-yi) or 1e-12)+xi:
                inside=not inside
            j=i
        return inside

    def _gizmo_geometry(self, view):
        solids=[e for e in self.selection if isinstance(e,Solid3D)]
        boxes=[e.bbox3d() for e in solids if e.bbox3d()]
        if not boxes:return None
        origin=((min(b[0] for b in boxes)+max(b[3] for b in boxes))*0.5,
                (min(b[1] for b in boxes)+max(b[4] for b in boxes))*0.5,
                (min(b[2] for b in boxes)+max(b[5] for b in boxes))*0.5)
        o=view.project3(*origin); L=56.0
        bases=dict(zip(("X","Y","Z"),view._basis3()))
        ends={a:QPointF(o.x()+b[0]*L,o.y()+b[1]*L) for a,b in bases.items()}
        # Plane handles sit close to the origin and are deliberately larger than
        # their visual fill, like a mechanical-CAD triad.
        handles={}
        for name,a1,a2 in (("XY","X","Y"),("XZ","X","Z"),("YZ","Y","Z")):
            b1,b2=bases[a1],bases[a2]
            area=abs(b1[0]*b2[1]-b1[1]*b2[0])
            if area<0.08:continue
            k1,k2=18.0,18.0
            poly=QPolygonF([QPointF(o.x()+b1[0]*7+b2[0]*7,o.y()+b1[1]*7+b2[1]*7),
                            QPointF(o.x()+b1[0]*(7+k1)+b2[0]*7,o.y()+b1[1]*(7+k1)+b2[1]*7),
                            QPointF(o.x()+b1[0]*(7+k1)+b2[0]*(7+k2),o.y()+b1[1]*(7+k1)+b2[1]*(7+k2)),
                            QPointF(o.x()+b1[0]*7+b2[0]*(7+k2),o.y()+b1[1]*7+b2[1]*(7+k2))])
            handles[name]=poly
        return origin,o,bases,ends,handles

    def _draw_gizmo(self, p, view=None):
        if not self.workspace_3d:return
        view=view or self.view; geo=self._gizmo_geometry(view)
        if geo is None:return
        origin,o,bases,ends,handles=geo
        colors={"X":QColor(230,75,75),"Y":QColor(80,210,100),"Z":QColor(75,135,245)}
        # Plane handles first so axes stay visually dominant.
        for name,poly in handles.items():
            c1,c2=colors[name[0]],colors[name[1]]
            fill=QColor((c1.red()+c2.red())//2,(c1.green()+c2.green())//2,(c1.blue()+c2.blue())//2,72)
            p.setPen(QPen(QColor(fill.red(),fill.green(),fill.blue(),170),1));p.setBrush(QBrush(fill));p.drawPolygon(poly)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for axis,q in ends.items():
            col=colors[axis];p.setPen(QPen(col,3));p.drawLine(o,q)
            # compact arrow head
            b=bases[axis];bl=math.hypot(b[0],b[1])
            if bl>1e-6:
                ux,uy=b[0]/bl,b[1]/bl;px,py=-uy,ux
                tip=q; back=QPointF(q.x()-ux*9,q.y()-uy*9)
                tri=QPolygonF([tip,QPointF(back.x()+px*4,back.y()+py*4),QPointF(back.x()-px*4,back.y()-py*4)])
                p.setBrush(QBrush(col));p.drawPolygon(tri);p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawText(q+QPointF(5,4),axis)
        p.setPen(QPen(QColor(235,235,235),1));p.setBrush(QBrush(QColor(45,55,65)));p.drawRect(QRectF(o.x()-5,o.y()-5,10,10));p.setBrush(Qt.BrushStyle.NoBrush)
        gd=self._gizmo_drag
        if gd is not None:
            tr=gd.get("translation",(0.0,0.0,0.0)); kind=gd.get("kind")
            if kind=="AXIS":
                label=f"{gd['constraint']}  {fmt(gd.get('amount',0.0),4)}"
                if not gd.get("numeric_entry"):
                    label += "   [TAB: 精確距離]"
                else:
                    buf=gd.get("numeric_buffer","")
                    label += "   距離: %s  [Enter 確認 / Esc 取消]" % (buf if buf else "_")
            else: label="%s  ΔX=%s  ΔY=%s  ΔZ=%s"%(gd.get("constraint","PLANE"),fmt(tr[0],4),fmt(tr[1],4),fmt(tr[2],4))
            self._tip(p,label,o.x()+18,o.y()-38,QColor(28,78,150,240))

    def _gizmo_hit(self, pos, view=None):
        if self.gen is not None or not self.workspace_3d:return None
        view=view or self.view;geo=self._gizmo_geometry(view)
        if geo is None:return None
        origin,o,bases,ends,handles=geo
        # Arrow tips/axes have priority over plane handles.
        best=None
        for axis,b in bases.items():
            q=ends[axis];vx,vy=q.x()-o.x(),q.y()-o.y();den=vx*vx+vy*vy
            if den<36:continue
            t=max(0.0,min(1.0,((pos.x()-o.x())*vx+(pos.y()-o.y())*vy)/den));px,py=o.x()+t*vx,o.y()+t*vy;d=math.hypot(pos.x()-px,pos.y()-py)
            # 11px actual target, while the drawn line stays thin.
            if d<=11 and t>=0.10 and (best is None or d<best[0]):best=(d,axis)
        if best is not None:return ("AXIS",best[1],origin)
        for name,poly in handles.items():
            if self._point_in_poly2(pos,poly):return ("PLANE",name,origin)
        return None

    def _axis_drag_parameter(self, view, pos, origin, axis):
        av=self._axis_world(axis);cam=view.camera_forward();d=_vdot(cam,av)
        n=(cam[0]-av[0]*d,cam[1]-av[1]*d,cam[2]-av[2]*d);n=_vnorm(n)
        if n is None:return None
        # Plane contains the selected axis and faces the camera as much as possible.
        plane=WorkPlane(origin,av,_vnorm(_vcross(n,av)) or (0,1,0),n)
        q=self.ray_plane(view,pos,plane)
        if q is None:return None
        return _vdot((q[0]-origin[0],q[1]-origin[1],q[2]-origin[2]),av)

    def _plane_drag_point(self, view, pos, origin, plane_name):
        a1=self._axis_world(plane_name[0]);a2=self._axis_world(plane_name[1]);n=_vnorm(_vcross(a1,a2))
        if n is None:return None
        plane=WorkPlane(origin,a1,a2,n)
        return self.ray_plane(view,pos,plane)

    def _gizmo_preview_translation(self, gd, tr):
        """Apply a lightweight, reversible Solid3D translation preview.

        Preview never touches the undo stack.  This is important for TAB numeric
        entry: the exact typed distance must replace the mouse preview rather than
        create a second edit/undo record.
        """
        current=gd.get("current_solids",[])
        newsol=[]
        tx,ty,tz=tr
        for old in gd.get("originals",[]):
            newsol.append(old.clone(vertices=[(x+tx,y+ty,z+tz) for x,y,z in old.vertices],brep_b64=""))
        mp={id(cur):ne for cur,ne in zip(current,newsol)}
        self.doc.entities=[mp.get(id(e),e) for e in self.doc.entities]
        self.selection=[mp.get(id(e),e) for e in self.selection]
        gd["current_solids"]=newsol
        gd["translation"]=tuple(float(v) for v in tr)
        self.invalidate();self.selectionChanged.emit()

    def _gizmo_restore_originals(self, gd):
        """Restore entities that were replaced by the transient gizmo preview."""
        current=gd.get("current_solids",[])
        originals=gd.get("originals",[])
        mp={id(cur):old for cur,old in zip(current,originals)}
        self.doc.entities=[mp.get(id(e),e) for e in self.doc.entities]
        self.selection=[mp.get(id(e),e) for e in self.selection]
        gd["current_solids"]=list(originals)

    def _finish_gizmo_translation(self, tr=None):
        """Commit the current gizmo translation exactly once, preserving BREP."""
        gd=self._gizmo_drag
        if gd is None:return False
        if tr is None:tr=gd.get("translation",(0.0,0.0,0.0))
        tr=tuple(float(v) for v in tr);mag=math.sqrt(sum(v*v for v in tr))
        self._gizmo_restore_originals(gd)
        if mag<=1e-12:
            self._gizmo_drag=None;self._restore_cursor();self.invalidate();self.selectionChanged.emit();return True
        self.doc.push_undo()
        tx,ty,tz=tr;final=[]
        for old in gd.get("originals",[]):
            ne=old.clone(vertices=[(x+tx,y+ty,z+tz) for x,y,z in old.vertices],brep_b64="")
            try:
                from .io_utils import _cq_shape_from_solid,_shape_to_brep_b64
                sh=_cq_shape_from_solid(old,1.0).translate((tx,ty,tz));ne=ne.clone(brep_b64=_shape_to_brep_b64(sh))
            except Exception:pass
            final.append(ne)
        mp={id(old):ne for old,ne in zip(gd.get("originals",[]),final)}
        self.doc.entities=[mp.get(id(e),e) for e in self.doc.entities]
        self.selection=[mp.get(id(e),e) for e in self.selection]
        self.doc.modified=True
        self._gizmo_drag=None;self._restore_cursor();self.changed();self.selectionChanged.emit();return True

    def gizmo_numeric_active(self):
        gd=self._gizmo_drag
        return bool(gd is not None and gd.get("kind")=="AXIS" and gd.get("numeric_entry"))

    def begin_gizmo_numeric(self):
        """TAB during an axis drag switches the triad to exact distance entry."""
        gd=self._gizmo_drag
        if gd is None:return False
        if gd.get("kind")!="AXIS":
            self.history.emit("<平面拖曳請直接使用滑鼠；TAB 精確距離適用於 X / Y / Z 軸。>")
            return True
        gd["numeric_entry"]=True
        gd["numeric_buffer"]=""
        gd["armed"]=True
        gd["mouse_down"]=False
        axis=gd.get("constraint","?")
        self.history.emit(f"<{axis} 軸精確移動：輸入距離後 Enter，例如 -20；Esc 取消。>")
        self.update();return True

    def accept_gizmo_numeric(self, text):
        """Consume command-line text while TAB numeric gizmo entry is active."""
        if not self.gizmo_numeric_active():return False
        v=parse_number(str(text))
        if v is None:
            self.history.emit("<請輸入有效距離，例如 -20、35.5。>")
            return True
        gd=self._gizmo_drag;axis=gd.get("constraint")
        av=self._axis_world(axis);tr=tuple(av[i]*v for i in range(3))
        gd["amount"]=v;gd["translation"]=tr
        self._finish_gizmo_translation(tr)
        self.history.emit(f"<{axis} 軸已精確移動 {fmt(v,4)}。>")
        return True

    def cancel_gizmo_drag(self):
        gd=self._gizmo_drag
        if gd is None:return False
        self._gizmo_restore_originals(gd)
        self._gizmo_drag=None;self._restore_cursor();self.invalidate();self.selectionChanged.emit()
        self.history.emit("<已取消 3D Gizmo 移動。>")
        return True

    def zoom_prev(self):
        if self.prev_views:
            st = self.prev_views.pop()
            if len(st) >= 6:
                self.view.scale, self.view.ox, self.view.oy, self.view.orientation, self.view.azimuth, self.view.elevation = st[:6]
            elif len(st) == 4:
                self.view.scale, self.view.ox, self.view.oy, self.view.orientation = st
            else:
                self.view.scale, self.view.ox, self.view.oy = st
            self.invalidate()
        else:
            self.msg("沒有上一個視圖。")

    def resizeEvent(self, e):
        old = e.oldSize()
        self.view.w, self.view.h = self.width(), self.height()
        if self._first_show:
            self._first_show = False
            if self.doc.entities:
                b = self.doc.extents() or (0.0, 0.0, 420.0, 297.0)
                self._fit(b, 0.92)
            else:
                self._fit((-20.0, -20.0, 440.0, 310.0))
        elif old.isValid():
            self.view.oy += self.height() - old.height()
        self.invalidate()

    # ================================================================ 指令驅動
    def busy(self):
        return self.gen is not None

    def start_command(self, name, gen=None):
        """啟動一個指令。gen 可直接給定（內部指令）。"""
        self.cancel(silent=True)
        fn = C.COMMANDS.get(name)
        if gen is None:
            if fn is None:
                return False
            gen = fn(self)
        self.cmd_name = name
        self._touched = False
        self._added = []
        self._keep = None
        self._preselect = list(self.selection) if self.selection else None
        self.gen = gen
        self.history.emit("指令: " + name)
        if (self.workspace_3d and self.view.orientation in ("FRONT","BACK","LEFT","RIGHT")
                and name.upper() in {"LINE","PLINE","CIRCLE","ARC","RECTANG","POLYGON","ELLIPSE","SPLINE"}):
            self.history.emit("提示：目前 2D 圖元仍屬於目前 2D/WCS 平面；側視圖要直接建立 3D 幾何請使用 BOX/CYLINDER 等 WorkPlane 基本體。")
        self._advance(None, first=True)
        return True

    def _advance(self, value, first=False, echo=None):
        if self.gen is None:
            return
        if self.req is not None and echo is not None:
            self.history.emit(self.prompt_plain() + " " + echo)
        if is_point(value):
            self.last_point = value
        try:
            req = next(self.gen) if first else self.gen.send(value)
        except StopIteration:
            self._finish()
            return
        except Exception as ex:
            traceback.print_exc()
            self.history.emit("指令發生錯誤: %s" % ex)
            self._finish()
            return
        self.req = req
        self._polar_sticky = None
        self._dyn_field = "DIST"
        self.pending = []
        self.box_start = None
        self.box_wait = False
        if req.kind == "point" and self._uses_3d_input():
            if req.base is None:
                self._input_plane_lock = None
            elif self._input_plane_lock is None:
                # Acquire once, then freeze through the rest of the operation.
                p=self.effective_work_plane(self._view_at(self.mouse)[0])
                # The frozen geometric plane must pass through the first/base point,
                # while typed absolute coordinates retain the original UCS origin.
                self._input_plane_lock = p.with_plane_origin(req.base if len(req.base)>=3 else (req.base[0],req.base[1],0.0))
        if req.kind == "select" and self._preselect:
            s, self._preselect = self._preselect, None
            self.selection = []
            self.history.emit("找到 %d 個" % len(s))
            self.previous_sel = list(s)
            self._advance(s)
            return
        self._preselect = None
        if req.kind != "select":
            self.selection = [] if self.selection else self.selection
        self._retarget()
        self.promptChanged.emit(self.prompt_html())
        self.selectionChanged.emit()
        self.update()

    def _finish(self):
        touched = self._touched
        self.gen = None
        self.req = None
        self.cmd_name = ""
        self.pending = []
        self.box_start = None
        self.snap_hit = None
        self.track = None
        self.temp_osnap = None
        self.otrack_points = []
        self.entity_shift = False
        self._touched = False
        self._input_plane_lock = None
        self._polar_sticky = None
        self.selection = [e for e in (self._keep or []) if any(e is x for x in self.doc.entities)]
        self._keep = None
        self.promptChanged.emit("")
        self.selectionChanged.emit()
        if touched:
            self.docChanged.emit()
            self.invalidate()
        self.update()

    def cancel(self, silent=False):
        if self.gen is not None:
            try:
                self.gen.close()
            except Exception:
                pass
            if not silent:
                self.history.emit("*取消*")
            self._finish()
        elif not silent:
            if self.selection or self.box_start is not None:
                self.selection = []
                self.box_start = None
                self.selectionChanged.emit()
                self.update()

    def enter(self):
        """Enter / 空白鍵 / 右鍵確認。"""
        r = self.req
        if r is None:
            return
        if r.kind == "select":
            s = list(self.pending)
            if s:
                self.previous_sel = list(s)
            self._advance(s, echo="")
        elif r.kind in ("point", "num", "kw", "text"):
            self._advance(r.default, echo="")
        else:
            self._advance(None, echo="")

    def prompt_plain(self):
        r = self.req
        if r is None:
            return ""
        s = r.prompt
        if r.keywords:
            s += " [" + "/".join("%s(%s)" % (n, k) for k, n in r.keywords) + "]"
        d = self._default_text()
        if d:
            s += " <%s>" % d
        return s + ":"

    def prompt_html(self):
        r = self.req
        if r is None:
            return ""
        s = html.escape(r.prompt)
        if r.keywords:
            s += " [" + "/".join('<a href="%s" style="color:#6fb4ff;text-decoration:none;">%s(%s)</a>' %
                                 (k, html.escape(n), k) for k, n in r.keywords) + "]"
        d = self._default_text()
        if d:
            s += " &lt;%s&gt;" % html.escape(d)
        return "<b>%s</b>&nbsp; %s:" % (html.escape(self.cmd_name.replace("_", " ")), s)

    def _default_text(self):
        d = self.req.default
        if d is None or self.req.kind in ("select", "entity") or d == "point":
            return ""
        if isinstance(d, bool):
            return ""
        if isinstance(d, (int, float)):
            return fmt(d, 4)
        return str(d)

    def feed_text(self, s):
        """指令行輸入。回傳 True 表示已處理。"""
        r = self.req
        if r is None:
            return False
        if r.kind == "text":
            self._advance(s if s.strip() else r.default, echo=s)
            return True
        s = s.strip()
        if not s:
            self.enter()
            return True
        up = s.upper()
        for k, n in r.keywords:
            if up == k.upper() or up == n.upper():
                self._advance(Kw(k), echo=s)
                return True
        if r.kind == "point":
            p = self.parse_point(s, r.base)
            if p is not None:
                self._advance(p, echo=s)
                return True
            v = parse_number(s)
            if v is not None:
                if r.number:
                    self._advance(v, echo=s)
                    return True
                if r.base is not None:
                    if self._uses_3d_input() and len(r.base)>=3 and isinstance(self.cur_pt,tuple) and len(self.cur_pt)>=3:
                        plane=self.effective_work_plane(self._view_at(self.mouse)[0]); bl=plane.to_local(r.base); cl=plane.to_local(self.cur_pt)
                        du,dv=cl[0]-bl[0],cl[1]-bl[1]; d=math.hypot(du,dv)
                        if d>G.EPS:
                            self._advance(plane.to_world((bl[0]+du/d*v,bl[1]+dv/d*v,bl[2])),echo=s); return True
                    else:
                        d = G.dist(r.base, self.cur_pt)
                        if d > G.EPS:
                            if getattr(self,"_dyn_field","DIST")=="ANGLE":
                                # TAB-selected angle field: typed number is the angle for
                                # this segment only; it does not mutate global Polar/Ortho.
                                self._advance(G.polar(r.base, v, d), echo=s)
                            else:
                                a = G.ang(r.base, self.cur_pt)
                                self._advance(G.polar(r.base, a, v), echo=s)
                            return True
            self.history.emit("需要點或選項關鍵字。")
            return True
        if r.kind == "num":
            v = parse_number(s)
            if v is None:
                self.history.emit("需要數值或選項關鍵字。")
            else:
                self._advance(v, echo=s)
            return True
        if r.kind == "select":
            if up in ("ALL", "A"):
                self._pend([e for e in self.doc.entities if self.doc.editable(e)])
            elif up in ("L", "LAST"):
                if self.doc.entities:
                    self._pend([self.doc.entities[-1]])
            elif up in ("P", "PREVIOUS"):
                self._pend([e for e in self.previous_sel if any(e is x for x in self.doc.entities)])
            else:
                self.history.emit("*無效的選取*  需要點，或 ALL / L(最後一個) / P(上一個)")
            return True
        self.history.emit("無效的選項關鍵字。")
        return True

    def parse_point(self, s, base=None):
        s=s.replace(" ",""); rel=s.startswith("@")
        if rel:
            s=s[1:]; base=base or self.last_point
        plane=self.effective_work_plane(self._view_at(self.mouse)[0]) if self._uses_3d_input() else None
        try:
            if "<" in s:
                d,a=s.split("<",1); d=float(d); a=float(a)
                if plane is not None:
                    bl=plane.to_local(base if base is not None else (0,0,0))
                    o=bl if rel else (0.0,0.0,0.0)
                    r=math.radians(a); return plane.to_world((o[0]+math.cos(r)*d,o[1]+math.sin(r)*d,o[2]))
                o=base if rel else (0.0,0.0); return G.polar(o,a,d)
            if "," in s:
                vals=s.split(","); x=float(vals[0].lstrip("#")); y=float(vals[1]); z=float(vals[2]) if len(vals)>=3 else 0.0
                if plane is not None:
                    if rel:
                        bl=plane.to_local(base if base is not None else (0,0,0)); return plane.to_world((bl[0]+x,bl[1]+y,bl[2]+z))
                    return plane.to_world((x,y,z))
                if len(vals)>=3:
                    if rel:
                        bz=(base[2] if base is not None and len(base)>=3 else 0.0); return ((base[0] if base else 0.0)+x,(base[1] if base else 0.0)+y,bz+z)
                    return (x,y,z)
                return (base[0]+x,base[1]+y) if rel else (x,y)
        except (ValueError,TypeError,IndexError):
            return None
        return None

    def click_keyword(self, key):
        if self.req is not None:
            self.feed_text(key)

    # ================================================================ 選取
    def _pend(self, ents, remove=False):
        if remove:
            ids = {id(e) for e in ents}
            n = len(self.pending)
            self.pending = [e for e in self.pending if id(e) not in ids]
            self.history.emit("移除 %d 個，共 %d 個" % (n - len(self.pending), len(self.pending)))
        else:
            ids = {id(e) for e in self.pending}
            new = [e for e in ents if id(e) not in ids]
            self.pending += new
            self.history.emit("找到 %d 個，共 %d 個" % (len(new), len(self.pending)))
        self.update()

    def pick(self, w, editable=True, types=None):
        tol = (PICKBOX + 2) / self.view.scale
        best = None
        for e in reversed(self.doc.entities):
            if types and not isinstance(e, types):
                continue
            if not (self.doc.editable(e) if editable else self.doc.visible(e)):
                continue
            if isinstance(e, Solid3D):
                # 3D 實體用目前視角的螢幕投影選取，不能拿 XY bbox 去判斷等角視圖。
                sx, sy = self.mouse.x(), self.mouse.y()
                best_px = float("inf"); best_edge = None
                n = len(e.vertices)
                # Display meshes can still contain many edges; cap hover work without
                # affecting geometry. Feature-edge generation keeps important edges first.
                stride=max(1,len(e.edges)//2500)
                for ei,(ia, ib) in enumerate(e.edges[::stride]):
                    if 0 <= ia < n and 0 <= ib < n:
                        a = self.view.project3(*e.vertices[ia]); bq = self.view.project3(*e.vertices[ib])
                        ax,ay,bx,by = a.x(),a.y(),bq.x(),bq.y()
                        vx,vy=bx-ax,by-ay; den=vx*vx+vy*vy
                        t=0.0 if den<1e-12 else max(0.0,min(1.0,((sx-ax)*vx+(sy-ay)*vy)/den))
                        px,py=ax+t*vx,ay+t*vy; dd=math.hypot(sx-px,sy-py)
                        if dd<best_px:best_px=dd;best_edge=ei*stride
                if best_px <= PICKBOX + 4:
                    self.last_subedge=(e,best_edge)
                    return e
                continue
            b = self.doc.bbox(e)
            if b is not None and (w[0] < b[0] - tol or w[0] > b[2] + tol or w[1] < b[1] - tol or w[1] > b[3] + tol):
                continue
            d = self.doc.hit_dist(e, w)
            if d == 0.0 and isinstance(e, Hatch):
                d = tol * 0.95
            if d <= tol and (best is None or d < best[0]):
                best = (d, e)
        return best[1] if best else None

    def pick_screen(self, pos, editable=True, types=None, view=None):
        """Depth-aware pixel-space picking for 3D/side/quad views.

        Solid hit-testing uses NumPy when available so Dynamic UCS and shaded face
        picking remain usable on large STL/STEP display meshes.  Wireframe styles
        intentionally do not expose face-interior hits.
        """
        view=view or self.view; sx,sy=float(pos.x()),float(pos.y()); tol=float(PICKBOX+5); best=None
        self.last_subedge=None; self.last_subface=None
        allow_faces=(str(self.visual_style).upper() in ("SHADED_EDGES","CONCEPTUAL")
                     or bool(getattr(self.s,"ducs",False)) or bool(getattr(self.req,"face_pick",False)))
        if self.orbiting or self.panning:
            allow_faces=False
        def segdist(a,b):
            ax,ay,bx,by=a.x(),a.y(),b.x(),b.y();vx,vy=bx-ax,by-ay;den=vx*vx+vy*vy
            t=0.0 if den<1e-12 else max(0.0,min(1.0,((sx-ax)*vx+(sy-ay)*vy)/den))
            return math.hypot(sx-(ax+t*vx),sy-(ay+t*vy))

        def solid_hit(e):
            n=len(e.vertices)
            if n==0:return None
            # Fast path: vectorize vertex projection, edge distance and triangle tests.
            try:
                import numpy as np
                hot=e.hit_arrays() if hasattr(e,"hit_arrays") else None
                if hot is None:
                    vv=np.asarray(e.vertices,dtype=float); ee_all=np.asarray(e.edges,dtype=np.int64) if e.edges else np.empty((0,2),dtype=np.int64); tt_all=np.empty((0,3),dtype=np.int64)
                else:
                    vv,ee_all,tt_all=hot
                bx,by,bz=view._basis3(); M=np.asarray([[bx[0],by[0],bz[0]],[bx[1],by[1],bz[1]]],dtype=float)
                pp=vv@M.T; pp[:,0]=view.ox+pp[:,0]*view.scale; pp[:,1]=view.oy+pp[:,1]*view.scale
                dmin=float('inf'); edge_idx=None; edge_depth=-float('inf')
                if e.edges:
                    ee=ee_all
                    ok=(ee[:,0]>=0)&(ee[:,0]<n)&(ee[:,1]>=0)&(ee[:,1]<n); ids=np.nonzero(ok)[0]; ee=ee[ok]
                    if len(ee):
                        a0=pp[ee[:,0]]; b0=pp[ee[:,1]]
                        near=(np.minimum(a0[:,0],b0[:,0])<=sx+tol)&(np.maximum(a0[:,0],b0[:,0])>=sx-tol)&(np.minimum(a0[:,1],b0[:,1])<=sy+tol)&(np.maximum(a0[:,1],b0[:,1])>=sy-tol)
                        ci=np.nonzero(near)[0]
                        if len(ci):
                            a=a0[ci];b=b0[ci];ec=ee[ci];idc=ids[ci];v=b-a;den=np.sum(v*v,axis=1)
                            w=np.asarray([sx,sy])-a;t=np.divide(np.sum(w*v,axis=1),den,out=np.zeros_like(den),where=den>1e-18);t=np.clip(t,0.0,1.0)
                            q=a+v*t[:,None];dd=np.hypot(q[:,0]-sx,q[:,1]-sy);j=int(np.argmin(dd));dmin=float(dd[j]);edge_idx=int(idc[j])
                            if dmin<=tol:
                                mid=(vv[ec[j,0]]+vv[ec[j,1]])*0.5;edge_depth=float(view.depth3(*mid))
                face_hit=None; face_depth=-float('inf')
                if allow_faces and e.faces:
                    # Mesh imports are predominantly triangles.  Handle those in one
                    # vectorized pass; non-triangular procedural faces use a bounded fallback.
                    tt=tt_all
                    if len(tt):
                        ok=(tt[:,0]>=0)&(tt[:,0]<n)&(tt[:,1]>=0)&(tt[:,1]<n)&(tt[:,2]>=0)&(tt[:,2]<n); tt=tt[ok]
                    if len(tt):
                        A0=pp[tt[:,0]];B0=pp[tt[:,1]];C0=pp[tt[:,2]]
                        # Cheap projected AABB rejection before barycentric math. On
                        # dense STL meshes this cuts ~80k triangles to the handful
                        # actually under the cursor.
                        near=(np.minimum(np.minimum(A0[:,0],B0[:,0]),C0[:,0])<=sx)&(np.maximum(np.maximum(A0[:,0],B0[:,0]),C0[:,0])>=sx)&(np.minimum(np.minimum(A0[:,1],B0[:,1]),C0[:,1])<=sy)&(np.maximum(np.maximum(A0[:,1],B0[:,1]),C0[:,1])>=sy)
                        ci=np.nonzero(near)[0]
                        if len(ci):
                            ttc=tt[ci];A=A0[ci];B=B0[ci];C=C0[ci];P=np.asarray([sx,sy])
                            v0=C-A;v1=B-A;v2=P-A
                            dot00=np.sum(v0*v0,axis=1);dot01=np.sum(v0*v1,axis=1);dot02=np.sum(v0*v2,axis=1);dot11=np.sum(v1*v1,axis=1);dot12=np.sum(v1*v2,axis=1)
                            den=dot00*dot11-dot01*dot01;inv=np.divide(1.0,den,out=np.zeros_like(den),where=np.abs(den)>1e-18)
                            uu=(dot11*dot02-dot01*dot12)*inv;vvv=(dot00*dot12-dot01*dot02)*inv;hit=(uu>=-1e-9)&(vvv>=-1e-9)&((uu+vvv)<=1.0+1e-9)&(np.abs(den)>1e-18)
                            if np.any(hit):
                                cf=view.camera_forward();dep=(vv[ttc].mean(axis=1)@np.asarray(cf,dtype=float));cand=np.nonzero(hit)[0];j=int(cand[np.argmax(dep[cand])]);face_depth=float(dep[j]);face_hit=tuple(int(x) for x in ttc[j])
                    # Small procedural ngons/quads only; avoid per-face QPolygonF on huge meshes.
                    if face_hit is None and len(e.faces)<=1024:
                        for face in e.faces:
                            ids=[int(i) for i in face if 0<=int(i)<n]
                            if len(ids)<3:continue
                            poly=QPolygonF([QPointF(float(pp[i,0]),float(pp[i,1])) for i in ids])
                            if poly.containsPoint(QPointF(sx,sy),Qt.FillRule.WindingFill):
                                dep=sum(view.depth3(*e.vertices[i]) for i in ids)/len(ids)
                                if dep>face_depth:face_depth=dep;face_hit=tuple(ids)
                if face_hit is not None and dmin>tol:dmin=tol*0.8
                if dmin<=tol:
                    depth=max(face_depth,edge_depth); return (dmin,depth,edge_idx,face_hit)
                return None
            except Exception:
                d=float('inf'); edge_idx=None; edge_depth=-float('inf')
                stride=max(1,len(e.edges)//3000)
                for ei,(ia,ib) in enumerate(e.edges[::stride]):
                    if 0<=ia<n and 0<=ib<n:
                        dd=segdist(view.project3(*e.vertices[ia]),view.project3(*e.vertices[ib]))
                        if dd<d:
                            d=dd;edge_idx=ei*stride; mid=tuple((e.vertices[ia][k]+e.vertices[ib][k])*0.5 for k in range(3));edge_depth=view.depth3(*mid)
                face_hit=None;face_depth=-float('inf')
                if allow_faces and len(e.faces)<=6000:
                    for face in e.faces:
                        ids=[int(i) for i in face if 0<=int(i)<n]
                        if len(ids)>=3:
                            poly=QPolygonF([view.project3(*e.vertices[i]) for i in ids])
                            if poly.containsPoint(QPointF(sx,sy),Qt.FillRule.WindingFill):
                                dep=sum(view.depth3(*e.vertices[i]) for i in ids)/len(ids)
                                if dep>face_depth:face_depth=dep;face_hit=tuple(ids)
                if face_hit is not None and d>tol:d=tol*0.8
                return (d,max(face_depth,edge_depth),edge_idx,face_hit) if d<=tol else None

        for e in reversed(self.doc.entities):
            if types and not isinstance(e,types):continue
            if not (self.doc.editable(e) if editable else self.doc.visible(e)):continue
            d=float('inf'); depth=-float('inf'); edge_idx=None; face_hit=None
            if isinstance(e,Solid3D):
                hit=solid_hit(e)
                if hit is None:continue
                d,depth,edge_idx,face_hit=hit
            else:
                for leaf in self.doc.expand(e):
                    if isinstance(leaf,Point):
                        q=view.project3(leaf.x,leaf.y,0); d=min(d,math.hypot(sx-q.x(),sy-q.y())); continue
                    if isinstance(leaf,(Text,MText)):
                        qs=[view.project3(x,y,0) for x,y in leaf.corners()]
                        for a,b in zip(qs,qs[1:]+qs[:1]):d=min(d,segdist(a,b))
                        continue
                    for pr in leaf.prims():
                        if pr[0]=='L':samples=[G.prim_start(pr),G.prim_end(pr)]
                        else:
                            L=max(G.prim_len(pr),1e-9);nn=max(6,min(72,int(L*view.scale/10)+1));samples=[G.prim_point(pr,L*i/nn) for i in range(nn+1)]
                        qs=[view.project3(x,y,0) for x,y in samples]
                        for a,b in zip(qs,qs[1:]):d=min(d,segdist(a,b))
                depth=0.0
            if d<=tol:
                score=(d,-depth)
                if best is None or score<best[0]:best=(score,e,edge_idx,face_hit)
        if best is None:return None
        _score,e,edge_idx,face_hit=best
        self.last_subedge=(e,edge_idx) if isinstance(e,Solid3D) and edge_idx is not None else None
        self.last_subface=(e,face_hit) if isinstance(e,Solid3D) and face_hit is not None else None
        return e

    def box_select(self, r, crossing):
        out = []
        doc = self.doc
        for e in doc.entities:
            if not doc.editable(e):
                continue
            b = doc.bbox(e)
            if b is not None:
                if b[0] >= r[0] and b[1] >= r[1] and b[2] <= r[2] and b[3] <= r[3]:
                    out.append(e)
                    continue
                if not crossing or b[2] < r[0] or b[0] > r[2] or b[3] < r[1] or b[1] > r[3]:
                    continue
            elif not crossing:
                continue
            hit = False
            for leaf in doc.expand(e):
                if isinstance(leaf, (Text, MText)):
                    cs = leaf.corners()
                    hit = any(G.seg_hits_rect(cs[i][0], cs[i][1], cs[(i + 1) % 4][0], cs[(i + 1) % 4][1], r)
                              for i in range(4))
                elif isinstance(leaf, Point):
                    hit = r[0] <= leaf.x <= r[2] and r[1] <= leaf.y <= r[3]
                else:
                    hit = any(G.prim_hits_rect(pr, r) for pr in leaf.prims())
                    if not hit and isinstance(leaf, Hatch):
                        hit = leaf.contains((r[0], r[1]))
                if hit:
                    break
            if hit:
                out.append(e)
        return out

    def box_select_screen(self, sr, crossing, view=None):
        """Window/crossing selection in projected screen space for any viewport."""
        view=view or self.view
        x0,y0,x1,y1=sr
        def inside(q):return x0<=q[0]<=x1 and y0<=q[1]<=y1
        def seg_hit(a,b):
            # Cohen/Sutherland-lite using existing geometry rectangle helper in pixel coordinates.
            return G.seg_hits_rect(a[0],a[1],b[0],b[1],sr)
        out=[]
        for e in self.doc.entities:
            if not self.doc.editable(e):continue
            points=[]; segs=[]
            if isinstance(e,Solid3D):
                points=[(view.project3(*v).x(),view.project3(*v).y()) for v in e.vertices]
                for ia,ib in e.edges:
                    if 0<=ia<len(points) and 0<=ib<len(points):segs.append((points[ia],points[ib]))
            else:
                for leaf in self.doc.expand(e):
                    if isinstance(leaf,Point):
                        q=view.project3(leaf.x,leaf.y,0.0); points.append((q.x(),q.y()));continue
                    if isinstance(leaf,(Text,MText)):
                        for x,y in leaf.corners():
                            q=view.project3(x,y,0.0);points.append((q.x(),q.y()))
                        continue
                    for pr in leaf.prims():
                        # sample curved primitives so isometric window selection matches their display
                        if pr[0]=='L': samples=[G.prim_start(pr),G.prim_end(pr)]
                        else:
                            L=max(G.prim_len(pr),1e-9); n=max(4,min(48,int(L*view.scale/16)+1))
                            samples=[G.prim_point(pr,L*i/n) for i in range(n+1)]
                        qs=[]
                        for x,y in samples:
                            q=view.project3(x,y,0.0);qs.append((q.x(),q.y()));points.append(qs[-1])
                        segs += list(zip(qs,qs[1:]))
            if not points:continue
            if crossing:
                hit=any(inside(q) for q in points) or any(seg_hit(a,b) for a,b in segs)
            else:
                hit=all(inside(q) for q in points)
            if hit:out.append(e)
        return out

    def select_all(self):
        if self.gen is None:
            self.selection = [e for e in self.doc.entities if self.doc.editable(e)]
            self.selectionChanged.emit()
            self.update()

    def set_selection(self, ents):
        self.selection = list(ents)
        self.selectionChanged.emit()
        self.update()

    def modify_selected(self, fn):
        """性質選項板用：對目前選集套用 fn(e) -> 新圖元。"""
        if not self.selection or self.gen is not None:
            return
        self.doc.push_undo()
        new = [fn(e) for e in self.selection]
        mp = {id(o): n for o, n in zip(self.selection, new)}
        self.doc.entities = [mp.get(id(e), e) for e in self.doc.entities]
        self.selection = new
        for e in new:
            self.doc.layer(e.layer)
        self.changed()
        self.selectionChanged.emit()

    def undo(self):
        self.cancel(silent=True)
        if self.doc.undo():
            self.selection = []
            self.history.emit("退回")
            self.selectionChanged.emit()
            self.changed()
        else:
            self.history.emit("沒有可退回的動作")

    def redo(self):
        self.cancel(silent=True)
        if self.doc.redo():
            self.selection = []
            self.history.emit("重做")
            self.selectionChanged.emit()
            self.changed()
        else:
            self.history.emit("沒有可重做的動作")

    # ================================================================ 鎖點
    def _wants_point(self):
        r = self.req
        return r is not None and r.kind == "point"

    def _retarget(self):
        """依目前滑鼠位置重新計算游標點（含鎖點、極座標、正交）。"""
        view, _vn, _vr = self._view_at(self.mouse)
        # Dynamic UCS acquires the visible solid face under the cursor before the
        # screen ray is intersected with the work plane.  NumPy-backed pick_screen()
        # keeps this practical on dense STL/STEP meshes.
        if self._wants_point() and self._uses_3d_input() and (getattr(self.s,"ducs",False) or bool(getattr(self.req,"face_pick",False))) and self._input_plane_lock is None:
            self.pick_screen(self.mouse,editable=False,types=(Solid3D,),view=view)
        w = self._screen_point(view, self.mouse)
        self.snap_hit = None
        self.track = None
        r = self.req
        if self._wants_point() and self._uses_3d_input():
            if w is None:return
            plane=self.effective_work_plane(view); base=r.base
            hit=self.find_osnap3d(view,self.mouse,base) if (self.s.osnap or self.temp_osnap) else None
            if hit:
                self.snap_hit=hit; w=hit[1]
            else:
                wl=plane.to_local(w); bl=plane.to_local(base) if base is not None else None
                u,v,ww=wl
                if bl is not None and self.s.otrack and self.otrack_points:
                    cand=None; inc=self.s.polar_inc if self.s.polar_inc>0 else 90.0
                    for origin3 in reversed(self.otrack_points):
                        ol=plane.to_local(origin3 if len(origin3)>=3 else (origin3[0],origin3[1],0.0))
                        for a0 in [i*inc for i in range(max(1,int(round(360.0/inc))))]:
                            a=math.radians(a0); ux,uy=math.cos(a),math.sin(a); t=(u-ol[0])*ux+(v-ol[1])*uy
                            if t<0:continue
                            qu,qv=ol[0]+ux*t,ol[1]+uy*t; off=math.hypot(u-qu,v-qv)*view.scale
                            if off<=8.0 and (cand is None or off<cand[0]):cand=(off,qu,qv,origin3,a0)
                    if cand is not None:
                        u,v=cand[1],cand[2]; self.track=(cand[3],cand[4]%360.0)
                if bl is not None and self.s.ortho:
                    if abs(u-bl[0])>=abs(v-bl[1]):v=bl[1]
                    else:u=bl[0]
                elif bl is not None and self.s.polar and math.hypot(u-bl[0],v-bl[1])>G.EPS:
                    inc=self.s.polar_inc; a=math.degrees(math.atan2(v-bl[1],u-bl[0]))%360.0; ta=round(a/inc)*inc
                    d=math.hypot(u-bl[0],v-bl[1]); off=abs(math.sin(math.radians(a-ta)))*d*view.scale
                    if off<=8.0 and math.cos(math.radians(a-ta))>0:
                        dd=d*math.cos(math.radians(a-ta)); u=bl[0]+math.cos(math.radians(ta))*dd; v=bl[1]+math.sin(math.radians(ta))*dd; self.track=(base,ta%360.0)
                if self.s.snap and self.track is None:
                    g=self.s.snap_size; u=round(u/g)*g; v=round(v/g)*g
                    if bl is not None and self.s.ortho:
                        if abs(u-bl[0])>=abs(v-bl[1]):v=bl[1]
                        else:u=bl[0]
                w=plane.to_world((u,v,ww))
            self.cur_pt=w; self.coordChanged.emit(float(w[0]),float(w[1]),float(w[2] if len(w)>=3 else 0.0)); return
        if self._wants_point():
            base = r.base
            hit = self.find_osnap(w, base) if (self.s.osnap or self.temp_osnap) else None
            if hit:
                self.snap_hit = hit
                w = hit[1]
                if self.s.otrack and hit[1] not in self.otrack_points:
                    self.otrack_points.append(hit[1])
                    del self.otrack_points[:-8]
            else:
                if self.s.otrack and self.otrack_points:
                    cand = None
                    inc = self.s.polar_inc if self.s.polar_inc > 0 else 90.0
                    for origin in reversed(self.otrack_points):
                        for a0 in [i * inc for i in range(max(1, int(round(360.0 / inc))))]:
                            a = math.radians(a0)
                            ux, uy = math.cos(a), math.sin(a)
                            t = (w[0] - origin[0]) * ux + (w[1] - origin[1]) * uy
                            if t < 0:
                                continue
                            q = (origin[0] + ux * t, origin[1] + uy * t)
                            off = G.dist(w, q) * view.scale
                            if off <= 8.0 and (cand is None or off < cand[0]):
                                cand = (off, q, origin, a0 % 360.0)
                    if cand is not None:
                        w = cand[1]
                        self.track = (cand[2], cand[3])
                if base is not None and self.s.ortho:
                    if abs(w[0] - base[0]) >= abs(w[1] - base[1]):
                        w = (w[0], base[1])
                    else:
                        w = (base[0], w[1])
                elif base is not None and self.s.polar and G.dist(base, w) > G.EPS:
                    inc = self.s.polar_inc if self.s.polar_inc > 0 else 90.0
                    a = G.ang(base, w); d = G.dist(base, w)
                    ta = self._polar_sticky
                    if ta is not None:
                        off = abs(math.sin(math.radians(a - ta))) * d * view.scale
                        if off > 14.0 or math.cos(math.radians(a - ta)) <= 0:
                            ta = None; self._polar_sticky = None
                    if ta is None:
                        candidate = round(a / inc) * inc
                        off = abs(math.sin(math.radians(a - candidate))) * d * view.scale
                        if off <= 8.0 and math.cos(math.radians(a - candidate)) > 0:
                            ta = candidate; self._polar_sticky = candidate
                    if ta is not None:
                        w = G.polar(base, ta, d * math.cos(math.radians(a - ta)))
                        self.track = (base, ta % 360.0)
                if self.s.snap and self.track is None:
                    g = self.s.snap_size
                    w = (round(w[0] / g) * g, round(w[1] / g) * g)
                    if base is not None and self.s.ortho:
                        if abs(w[0] - base[0]) >= abs(w[1] - base[1]):
                            w = (w[0], base[1])
                        else:
                            w = (base[0], w[1])
        self.cur_pt = w
        self.coordChanged.emit(w[0], w[1], w[2] if isinstance(w,tuple) and len(w)>=3 else 0.0)

    def find_osnap3d(self, view, pos, base=None):
        """Pixel-space OSNAP for Solid3D and 2D references in a 3D viewport.

        Orthographic/isometric views cannot use a single XY inverse coordinate to judge
        proximity.  Candidates are therefore projected into the active viewport and
        compared in pixels, while the returned point keeps its original XYZ coordinate.
        This is what makes MOVE3D/ROTATE3D base points usable on real CAD solids.
        """
        modes={self.temp_osnap} if self.temp_osnap else self.s.modes
        if not modes or "NONE" in modes:return None
        sx,sy=float(pos.x()),float(pos.y());tol=float(APERTURE+2)
        best=None
        pri={"END":0,"MID":1,"CEN":2,"GCE":3,"QUA":4,"INT":5,"INS":6,"PER":7,"TAN":8,"NEA":9}

        def offer(kind,q):
            nonlocal best
            if kind not in modes:return
            try:
                p3=(float(q[0]),float(q[1]),float(q[2]) if len(q)>=3 else 0.0)
                sp=view.project3(*p3);d=math.hypot(sx-sp.x(),sy-sp.y())
                if d>tol:return
                depth=view.depth3(*p3)
                score=(d,pri.get(kind,20),-depth)
                if best is None or score<best[0]:best=(score,kind,p3)
            except Exception:return

        def projected_bbox_near(e,margin=18.0):
            b=e.bbox3d()
            if not b:return True
            pts=[(x,y,z) for x in (b[0],b[3]) for y in (b[1],b[4]) for z in (b[2],b[5])]
            qs=[view.project3(*q) for q in pts];xs=[q.x() for q in qs];ys=[q.y() for q in qs]
            return min(xs)-margin<=sx<=max(xs)+margin and min(ys)-margin<=sy<=max(ys)+margin

        solids_seen=0
        for e in reversed(self.doc.entities):
            if not self.doc.visible(e):continue
            if isinstance(e,Solid3D):
                if not projected_bbox_near(e):continue
                solids_seen+=1
                try:cands=e.snap_points3d(6000)
                except Exception:cands=[]
                for kind,q in cands:offer(kind,q)
                # NEA follows the visible/feature edge cache and interpolates the true
                # XYZ location instead of returning a flattened XY approximation.
                if "NEA" in modes and e.edges:
                    n=len(e.vertices);edges=e.edges;stride=max(1,len(edges)//3000)
                    for ia,ib in edges[::stride]:
                        if not (0<=int(ia)<n and 0<=int(ib)<n):continue
                        a=e.vertices[int(ia)];b=e.vertices[int(ib)];pa=view.project3(*a);pb=view.project3(*b)
                        vx,vy=pb.x()-pa.x(),pb.y()-pa.y();den=vx*vx+vy*vy
                        t=0.0 if den<1e-12 else max(0.0,min(1.0,((sx-pa.x())*vx+(sy-pa.y())*vy)/den))
                        px,py=pa.x()+t*vx,pa.y()+t*vy
                        if math.hypot(sx-px,sy-py)<=tol:
                            offer("NEA",(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t))
                if solids_seen>=40:break
            else:
                # Existing 2D references remain snap targets in 3D views at Z=0.
                try:
                    for kind,x,y in self.doc.snaps(e):offer(kind,(x,y,0.0))
                except Exception:pass
        return (best[1],best[2]) if best else None

    def find_osnap(self, w, base=None):
        modes = {self.temp_osnap} if self.temp_osnap else self.s.modes
        tol = APERTURE / self.view.scale
        doc = self.doc
        near = []
        for e in doc.entities:
            if not doc.visible(e):
                continue
            b = doc.bbox(e)
            if b is not None and (w[0] < b[0] - tol or w[0] > b[2] + tol or w[1] < b[1] - tol or w[1] > b[3] + tol):
                continue
            near.append(e)
            if len(near) > 60:
                break
        best = None

        def offer(kind, p, d):
            nonlocal best
            if d <= tol and (best is None or d < best[0]):
                best = (d, kind, p)

        prims = []
        for e in near:
            for k, x, y in doc.snaps(e):
                if k in modes:
                    offer(k, (x, y), G.dist(w, (x, y)))
            for leaf in doc.expand(e):
                if isinstance(leaf, (Text, MText, Hatch, Point)):
                    continue
                for pr in leaf.prims():
                    d, q = G.nearest_on_prim(w, pr)
                    if d <= tol:
                        prims.append((pr, q, d))
                        if "CEN" in modes and pr[0] == 'A' and len(leaf.prims()) <= 64:
                            offer("CEN", (pr[1], pr[2]), tol * 0.9)
        prims = prims[:40]
        if "INT" in modes:
            for i in range(len(prims)):
                for j in range(i + 1, len(prims)):
                    for ip in G.intersect(prims[i][0], prims[j][0]):
                        offer("INT", ip, G.dist(w, ip) * 0.8)
        if base is not None:
            for pr, q, d in prims:
                # 垂直點／切點：游標停在物件上就成立（跟中心點一樣是「延遲」鎖點）
                if "PER" in modes:
                    for f in G.perp_foot(base, pr):
                        offer("PER", f, min(G.dist(w, f), tol * 0.95))
                if "TAN" in modes:
                    fs = G.tangent_pts(base, pr)
                    if fs:
                        f = min(fs, key=lambda t: G.dist(w, t))
                        offer("TAN", f, min(G.dist(w, f), tol * 0.92))
        if best is None and "NEA" in modes and prims:
            pr, q, d = min(prims, key=lambda x: x[2])
            best = (d, "NEA", q)
        return (best[1], best[2]) if best else None

    # ================================================================ 繪製
    def _ensure_cache(self):
        # During orbit/gizmo drag render a lighter LOD.  On release invalidate() is
        # called again, restoring the full-quality cached view.  This prevents large
        # imported STL/STEP files from freezing or crashing the GUI while dragging.
        self.renderer.interactive = bool(self.orbiting or self.panning or self._gizmo_drag is not None)
        dpr = self.devicePixelRatioF()
        if self._cache is not None:
            return
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(BG)
        p = QPainter(pm)
        if self.quad_view and self.workspace_3d:
            self.renderer.dark = True
            self.renderer.show_lw = self.s.lw
            self.renderer.visual_style = self.visual_style
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            for r, name, qv in self._quad_views():
                p.save(); p.setClipRect(r); self.renderer.paint(p, qv, cull=False); p.restore()
                p.setPen(QPen(QColor(92,105,120),1)); p.drawRect(r.adjusted(0,0,-1,-1))
                labels={"TOP":"上視","FRONT":"前視","RIGHT":"右視","SEISO":"東南等角"}
                p.setPen(QPen(QColor(205,215,225),1)); p.drawText(QPointF(r.left()+8,r.top()+18), labels.get(name,name))
            p.end(); self._cache=pm; return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._draw_grid(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.renderer.dark = True
        self.renderer.show_lw = self.s.lw
        self.renderer.visual_style = self.visual_style
        self.view.w, self.view.h = self.width(), self.height()
        self.renderer.paint(p, self.view)
        p.end()
        self._cache = pm

    def _draw_grid(self, p):
        v = self.view
        mode=str(getattr(self,"ucs_mode","WCS") or "WCS").upper()
        # Drafting TOP/WCS keeps the traditional fast screen-aligned grid.  A real
        # UCS plane is used in 3D so the grid and point input agree with each other.
        principal = "XY"
        if mode=="FRONT": principal="XZ"
        elif mode=="RIGHT": principal="YZ"
        elif mode=="TOP": principal="XY"
        elif mode=="VIEW": principal="VIEW"

        grid_visible=True
        if mode=="WCS" and self.workspace_3d:
            grid_visible=abs(_vdot((0.0,0.0,1.0),v.camera_forward()))>1e-7
        if self.s.grid and grid_visible:
            g=max(self.s.grid_size,1e-9)
            while g*v.scale<9:g*=5
            while g*v.scale>220:g/=5

            if v.orientation=="TOP" and principal=="XY":
                x0,y0,x1,y1=v.world_rect()
                for major in (False,True):
                    p.setPen(QPen(QColor(52,61,72) if major else QColor(41,49,59),1))
                    for i in range(math.floor(x0/g),math.ceil(x1/g)+1):
                        if (i%5==0)==major:
                            x=int(round(v.ox+i*g*v.scale));p.drawLine(x,0,x,v.h)
                    for j in range(math.floor(y0/g),math.ceil(y1/g)+1):
                        if (j%5==0)==major:
                            y=int(round(v.oy-j*g*v.scale));p.drawLine(0,y,v.w,y)
            else:
                bx,by,bz=v._basis3()
                # world vectors corresponding to device right/down; they span VIEW UCS.
                vr=(bx[0],by[0],bz[0]); vd=(bx[1],by[1],bz[1])
                if principal=="XZ":
                    gp=lambda a,b:v.project3(a,0,b)
                    c3=v.screen_to_plane3(v.w/2,v.h/2,"XZ");ca,cb=c3[0],c3[2]
                elif principal=="YZ":
                    gp=lambda a,b:v.project3(0,a,b)
                    c3=v.screen_to_plane3(v.w/2,v.h/2,"YZ");ca,cb=c3[1],c3[2]
                elif principal=="VIEW":
                    gp=lambda a,b:v.project3(a*vr[0]+b*vd[0],a*vr[1]+b*vd[1],a*vr[2]+b*vd[2])
                    q0,_=v.screen_ray(v.w/2,v.h/2);ca=sum(q0[k]*vr[k] for k in range(3));cb=sum(q0[k]*vd[k] for k in range(3))
                else:
                    gp=lambda a,b:v.project3(a,b,0)
                    c3=v.screen_to_plane3(v.w/2,v.h/2,"XY");ca,cb=c3[0],c3[1]
                span=max(v.w,v.h)/max(v.scale,1e-9)*0.72
                a0,a1=ca-span,ca+span;b0,b1=cb-span,cb+span
                i0,i1=math.floor(a0/g),math.ceil(a1/g);j0,j1=math.floor(b0/g),math.ceil(b1/g)
                while i1-i0>140 or j1-j0>140:
                    g*=5;i0,i1=math.floor(a0/g),math.ceil(a1/g);j0,j1=math.floor(b0/g),math.ceil(b1/g)
                for major in (False,True):
                    p.setPen(QPen(QColor(52,61,72) if major else QColor(41,49,59),1))
                    for i in range(i0,i1+1):
                        if (i%5==0)==major:p.drawLine(gp(i*g,b0),gp(i*g,b1))
                    for j in range(j0,j1+1):
                        if (j%5==0)==major:p.drawLine(gp(a0,j*g),gp(a1,j*g))

        # Axis lines match the active UCS plane instead of always pretending it is WCS XY.
        L=max(v.w,v.h)/max(v.scale,1e-9)
        if principal=="XZ":
            p.setPen(QPen(QColor(110,46,46),1));p.drawLine(v.project3(-L,0,0),v.project3(L,0,0))
            p.setPen(QPen(QColor(55,85,150),1));p.drawLine(v.project3(0,0,-L),v.project3(0,0,L))
        elif principal=="YZ":
            p.setPen(QPen(QColor(46,104,52),1));p.drawLine(v.project3(0,-L,0),v.project3(0,L,0))
            p.setPen(QPen(QColor(55,85,150),1));p.drawLine(v.project3(0,0,-L),v.project3(0,0,L))
        elif principal=="VIEW":
            bx,by,bz=v._basis3();vr=(bx[0],by[0],bz[0]);vd=(bx[1],by[1],bz[1])
            gp=lambda a,b:v.project3(a*vr[0]+b*vd[0],a*vr[1]+b*vd[1],a*vr[2]+b*vd[2])
            p.setPen(QPen(QColor(110,80,80),1));p.drawLine(gp(-L,0),gp(L,0))
            p.setPen(QPen(QColor(70,105,80),1));p.drawLine(gp(0,-L),gp(0,L))
        else:
            o=v.w2s(0,0)
            if v.orientation=="TOP":
                if -1<=o.y()<=v.h+1:p.setPen(QPen(QColor(110,46,46),1));p.drawLine(0,int(round(o.y())),v.w,int(round(o.y())))
                if -1<=o.x()<=v.w+1:p.setPen(QPen(QColor(46,104,52),1));p.drawLine(int(round(o.x())),0,int(round(o.x())),v.h)
            else:
                p.setPen(QPen(QColor(110,46,46),1));p.drawLine(v.project3(-L,0,0),v.project3(L,0,0))
                p.setPen(QPen(QColor(46,104,52),1));p.drawLine(v.project3(0,-L,0),v.project3(0,L,0))

    def paintEvent(self, ev):
        self._ensure_cache()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.quad_view and self.workspace_3d:
            rreq=self.req; sel=self.pending if (rreq is not None and rreq.kind=="select") else self.selection
            active_view,active_name,active_rect=self._view_at(self.mouse)
            for rect,name,qv in self._quad_views():
                p.save();p.setClipRect(rect)
                if sel:
                    glow=QPen(QColor(80,160,255,150),4.0);glow.setCosmetic(True)
                    for ent0 in sel[:3000]:self.renderer.draw_entity(p,ent0,qv,glow,QColor(150,200,255))
                if self.hover is not None and name==active_name and not any(self.hover is x for x in sel):
                    hp=QPen(QColor(200,225,255,130),3.0);hp.setCosmetic(True);self.renderer.draw_entity(p,self.hover,qv,hp,QColor(220,235,255))
                if name==active_name and rreq is not None and rreq.kind=="point" and self.inside:
                    if rreq.preview is not None:
                        try: ents=rreq.preview(self.cur_pt) or []
                        except Exception: ents=[]
                        if ents:self.renderer.paint(p,qv,entities=ents,cull=False);p.setWorldTransform(QTransform())
                    if rreq.base is not None and rreq.rubber:
                        def p3(q):return (q[0],q[1],q[2] if isinstance(q,tuple) and len(q)>=3 else 0.0)
                        p.setPen(QPen(QColor(255,176,64),1,Qt.PenStyle.DashLine));p.drawLine(qv.project3(*p3(rreq.base)),qv.project3(*p3(self.cur_pt)))
                p.restore()
            p.save();p.setClipRect(active_rect);self._draw_gizmo(p,active_view);p.restore()
            self._draw_box(p)
            if self.inside and not self.panning and not self.orbiting:
                # Cursor remains visible in the active engineering viewport.
                x,y=self.mouse.x(),self.mouse.y();arm=max(28.0,active_rect.height()*0.06);p.setPen(QPen(QColor(235,240,245),1))
                p.drawLine(QPointF(max(active_rect.left(),x-arm),y),QPointF(min(active_rect.right(),x+arm),y));p.drawLine(QPointF(x,max(active_rect.top(),y-arm)),QPointF(x,min(active_rect.bottom(),y+arm)))
                p.drawRect(QRectF(x-PICKBOX,y-PICKBOX,2*PICKBOX,2*PICKBOX))
            p.end(); return
        v = self.view
        r = self.req
        # 亮顯：選集 / 暫存選集 / 游標下的物件
        sel = self.pending if (r is not None and r.kind == "select") else self.selection
        if sel:
            glow = QPen(QColor(80, 160, 255, 150), 4.0)
            glow.setCosmetic(True)
            for e in sel[:3000]:
                self.renderer.draw_entity(p, e, v, glow, QColor(150, 200, 255))
        if self.hover is not None and not any(self.hover is x for x in sel):
            hp = QPen(QColor(200, 225, 255, 130), 3.0)
            hp.setCosmetic(True)
            self.renderer.draw_entity(p, self.hover, v, hp, QColor(220, 235, 255))
        self._draw_gizmo(p)
        # 預覽
        if r is not None and r.kind == "point" and self.inside:
            if r.preview is not None:
                try:
                    ents = r.preview(self.cur_pt) or []
                except Exception:
                    ents = []
                if ents:
                    self.renderer.paint(p, v, entities=ents, cull=False)
                    p.setWorldTransform(QTransform())
            if r.base is not None and r.rubber:
                pen = QPen(QColor(255, 176, 64), 1, Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.drawLine(self._project_point(v, r.base), self._project_point(v, self.cur_pt))
        self._draw_track(p)
        self._draw_box(p)
        self._draw_grips(p)
        self._draw_snap(p)
        self._draw_ucs(p)
        if self.workspace_3d:
            self._draw_viewcube(p)
        if self.inside and not self.panning and not self.orbiting:
            self._draw_cursor(p)
            self._draw_dyn(p)
        p.end()

    def _draw_box(self, p):
        if self.box_start is None:
            return
        a, b = self.box_start, self.mouse
        crossing = b.x() < a.x()
        rc = QRectF(a, b).normalized()
        if crossing:
            p.setPen(QPen(QColor(150, 230, 170), 1, Qt.PenStyle.DashLine))
            p.setBrush(QBrush(QColor(40, 170, 90, 50)))
        else:
            p.setPen(QPen(QColor(120, 170, 255), 1))
            p.setBrush(QBrush(QColor(40, 100, 220, 50)))
        p.drawRect(rc)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_grips(self, p):
        if self.gen is not None or not self.selection:
            return
        for e in self.selection[:300]:
            for i, g in enumerate(e.grips()):
                s = self.view.w2s(*g)
                hot = self.hover_grip is not None and self.hover_grip[0] is e and self.hover_grip[1] == i
                p.setPen(QPen(QColor(20, 30, 45), 1))
                p.setBrush(QBrush(QColor(255, 120, 110) if hot else QColor(30, 130, 255)))
                p.drawRect(QRectF(s.x() - GRIP, s.y() - GRIP, 2 * GRIP, 2 * GRIP))
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_snap(self, p):
        if self.snap_hit is None:
            return
        kind, pt = self.snap_hit
        view,_vn,_vr=self._view_at(self.mouse)
        s = self._project_point(view,pt)
        x, y, r = s.x(), s.y(), 6.0
        p.setPen(QPen(QColor(70, 230, 120), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "END":
            p.drawRect(QRectF(x - r, y - r, 2 * r, 2 * r))
        elif kind == "MID":
            p.drawPolygon(QPolygonF([QPointF(x, y - r), QPointF(x + r, y + r), QPointF(x - r, y + r)]))
        elif kind == "CEN":
            p.drawEllipse(s, r, r)
        elif kind == "GCE":
            p.drawEllipse(s, r, r)
            p.drawLine(QPointF(x - r, y), QPointF(x + r, y))
            p.drawLine(QPointF(x, y - r), QPointF(x, y + r))
        elif kind == "NOD":
            p.drawEllipse(s, r, r)
            p.drawLine(QPointF(x - r, y - r), QPointF(x + r, y + r))
            p.drawLine(QPointF(x - r, y + r), QPointF(x + r, y - r))
        elif kind == "QUA":
            p.drawPolygon(QPolygonF([QPointF(x, y - r), QPointF(x + r, y), QPointF(x, y + r), QPointF(x - r, y)]))
        elif kind == "INT":
            p.drawLine(QPointF(x - r, y - r), QPointF(x + r, y + r))
            p.drawLine(QPointF(x - r, y + r), QPointF(x + r, y - r))
        elif kind == "INS":
            p.drawPolyline(QPolygonF([QPointF(x - r, y - r), QPointF(x, y - r), QPointF(x, y), QPointF(x + r, y),
                                      QPointF(x + r, y + r), QPointF(x, y + r), QPointF(x, y), QPointF(x - r, y),
                                      QPointF(x - r, y - r)]))
        elif kind == "PER":
            p.drawPolyline(QPolygonF([QPointF(x - r, y - r), QPointF(x - r, y + r), QPointF(x + r, y + r)]))
            p.drawPolyline(QPolygonF([QPointF(x - r, y), QPointF(x, y), QPointF(x, y + r)]))
        elif kind == "TAN":
            p.drawEllipse(s, r, r)
            p.drawLine(QPointF(x - r, y - r), QPointF(x + r, y - r))
        else:
            p.drawPolygon(QPolygonF([QPointF(x - r, y - r), QPointF(x + r, y - r), QPointF(x - r, y + r),
                                     QPointF(x + r, y + r)]))
        self._tip(p, SNAP_NAMES.get(kind, kind), x + 14, y - 30)

    def _tip(self, p, text, x, y, bg=QColor(58, 66, 80, 235), fg=QColor(235, 240, 245)):
        f = QFont(font_family())
        f.setPixelSize(12)
        p.setFont(f)
        fm = QFontMetricsF(f)
        w, h = fm.horizontalAdvance(text) + 12, fm.height() + 6
        x = min(max(2.0, x), self.width() - w - 2)
        y = min(max(2.0, y), self.height() - h - 2)
        p.setPen(QPen(QColor(120, 132, 150), 1))
        p.setBrush(QBrush(bg))
        p.drawRect(QRectF(x, y, w, h))
        p.setPen(QPen(fg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawText(QPointF(x + 6, y + 3 + fm.ascent()), text)
        return w, h

    def _draw_track(self, p):
        if self.track is None or not self.inside:
            return
        base, a = self.track
        s = self.view.w2s(*base)
        far = max(self.width(), self.height()) * 2.0
        e = QPointF(s.x() + far * math.cos(math.radians(a)), s.y() - far * math.sin(math.radians(a)))
        p.setPen(QPen(QColor(70, 230, 120), 1, Qt.PenStyle.DotLine))
        p.drawLine(s, e)

    def _draw_ucs(self, p):
        # AutoCAD 風格 UCS 圖示：依目前標準視角顯示 X/Y/Z 三軸。
        o = QPointF(30.0, self.height() - 30.0)
        L = 42.0
        f = QFont(font_family()); f.setPixelSize(11); p.setFont(f)
        bx, by, bz = self.view._basis3()
        axes = ((bx, QColor(210,70,70), "X"), (by, QColor(80,190,90), "Y"), (bz, QColor(80,135,235), "Z"))
        for b, col, lab in axes:
            # basis 已是 screen-y 方向；等角視圖三軸會自然呈現立體感。
            q = QPointF(o.x()+b[0]*L, o.y()+b[1]*L)
            if abs(b[0]) + abs(b[1]) < 1e-9:
                continue
            p.setPen(QPen(col, 2)); p.drawLine(o, q)
            p.drawText(QPointF(q.x()+3, q.y()+4), lab)
        p.setPen(QPen(QColor(210,215,220),1)); p.setBrush(QBrush(QColor(33,40,48)))
        p.drawRect(QRectF(o.x()-4,o.y()-4,8,8)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(180,190,200),1)); p.drawText(QPointF(o.x()-8,o.y()+20), self.ucs_mode + (" DUCS" if getattr(self.s,"ducs",False) else ""))

    def _draw_viewcube(self, p):
        """Compact clickable ViewCube-style navigation aid for the 3D workspace."""
        x = self.width() - 112.0
        y = 24.0
        c = QPointF(x + 48.0, y + 42.0)
        top = QPolygonF([QPointF(c.x(),c.y()-28), QPointF(c.x()+28,c.y()-14),
                         QPointF(c.x(),c.y()), QPointF(c.x()-28,c.y()-14)])
        left = QPolygonF([QPointF(c.x()-28,c.y()-14), QPointF(c.x(),c.y()),
                          QPointF(c.x(),c.y()+30), QPointF(c.x()-28,c.y()+15)])
        right = QPolygonF([QPointF(c.x()+28,c.y()-14), QPointF(c.x(),c.y()),
                           QPointF(c.x(),c.y()+30), QPointF(c.x()+28,c.y()+15)])
        p.setPen(QPen(QColor(205,215,225),1))
        p.setBrush(QBrush(QColor(93,103,116,220))); p.drawPolygon(top)
        p.setBrush(QBrush(QColor(71,81,94,220))); p.drawPolygon(left)
        p.setBrush(QBrush(QColor(82,92,105,220))); p.drawPolygon(right)
        p.setPen(QPen(QColor(240,243,247),1))
        p.drawText(QPointF(c.x()-9,c.y()-12), "上")
        p.drawText(QPointF(c.x()-23,c.y()+17), "前")
        p.drawText(QPointF(c.x()+9,c.y()+17), "右")
        p.setPen(QPen(QColor(155,165,176),1))
        p.drawText(QPointF(x+19,y+88), "ViewCube")

    def _viewcube_hit(self, pos):
        if not self.workspace_3d:
            return False
        x = self.width() - 112.0; y = 24.0
        if not (x+12 <= pos.x() <= x+84 and y+8 <= pos.y() <= y+78):
            return False
        # Three broad face zones; corner click returns to the preferred SE isometric view.
        lx, ly = pos.x()-(x+48), pos.y()-(y+42)
        if ly < -6:
            self.set_view_orientation("TOP", fit=False)
        elif lx > 4:
            self.set_view_orientation("RIGHT", fit=False)
        elif lx < -4:
            self.set_view_orientation("FRONT", fit=False)
        else:
            self.set_view_orientation("SEISO", fit=False)
        return True

    def _draw_cursor(self, p):
        r = self.req
        view, _vn, _vr = self._view_at(self.mouse)
        if self.snap_hit is not None:
            c = self._project_point(view, self.snap_hit[1])
        elif self._wants_point():
            c = self._project_point(view, self.cur_pt)
        else:
            c = self.mouse
        x, y = c.x(), c.y()
        arm = max(42.0, self.height() * 0.05)
        show_cross = r is None or r.kind == "point" or (r.kind == "entity" and r.default == "point")
        show_box = r is None or r.kind in ("select", "entity")
        p.setPen(QPen(QColor(235, 240, 245), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        gap = PICKBOX if show_box else 0
        if show_cross:
            p.drawLine(QPointF(x - arm, y), QPointF(x - gap, y))
            p.drawLine(QPointF(x + gap, y), QPointF(x + arm, y))
            p.drawLine(QPointF(x, y - arm), QPointF(x, y - gap))
            p.drawLine(QPointF(x, y + gap), QPointF(x, y + arm))
        if show_box:
            p.drawRect(QRectF(x - PICKBOX, y - PICKBOX, 2 * PICKBOX, 2 * PICKBOX))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def _draw_dyn(self, p):
        r = self.req
        if not self.s.dyn or r is None:
            return
        x, y = self.mouse.x() + 20, self.mouse.y() + 24
        text = r.prompt
        w, h = self._tip(p, text, x, y)
        if r.kind == "point" and r.base is not None:
            if isinstance(r.base, tuple) and len(r.base) >= 3 and isinstance(self.cur_pt, tuple) and len(self.cur_pt) >= 3:
                dx=self.cur_pt[0]-r.base[0]; dy=self.cur_pt[1]-r.base[1]; dz=self.cur_pt[2]-r.base[2]
                d=math.sqrt(dx*dx+dy*dy+dz*dz)
                label="距離: %s   ΔX=%s ΔY=%s ΔZ=%s" % (fmt(d,4),fmt(dx,4),fmt(dy,4),fmt(dz,4))
            else:
                d, a = G.dist(r.base, self.cur_pt), G.ang(r.base, self.cur_pt)
                label = ("極座標: " if self.track else "") + "%s < %s°" % (fmt(d, 4), fmt(a, 2))
                label += "   [TAB: %s]" % ("角度" if self._dyn_field=="ANGLE" else "距離")
                if self.s.polar:
                    label += "   Polar %g°" % self.s.polar_inc
            self._tip(p, label, x, y + h + 3, QColor(28, 78, 150, 240))
        elif r.kind == "point":
            if isinstance(self.cur_pt, tuple) and len(self.cur_pt) >= 3:
                label="%s , %s , %s" % (fmt(self.cur_pt[0],4),fmt(self.cur_pt[1],4),fmt(self.cur_pt[2],4))
            else:
                label="%s , %s" % (fmt(self.cur_pt[0],4),fmt(self.cur_pt[1],4))
            _w,_h=self._tip(p, label, x, y + h + 3, QColor(28, 78, 150, 240))
            if bool(getattr(r,"face_pick",False)) and self.last_subface is not None and isinstance(self.cur_pt,tuple) and len(self.cur_pt)>=3:
                try:
                    frame=self.face_frame3d()
                    if frame is None:raise ValueError("no face frame")
                    cen,u,v,n=frame;d=(self.cur_pt[0]-cen[0],self.cur_pt[1]-cen[1],self.cur_pt[2]-cen[2])
                    flabel="面局部：U=%s  V=%s  N=%s"%(fmt(_vdot(d,u),4),fmt(_vdot(d,v),4),fmt(_vdot(d,n),4))
                    self._tip(p,flabel,x,y+h+_h+6,QColor(70,75,82,235))
                except Exception:pass

    # ================================================================ 滑鼠
    def _grip_at(self, pos):
        if self.gen is not None:
            return None
        for e in self.selection[:300]:
            for i, g in enumerate(e.grips()):
                s = self.view.w2s(*g)
                if abs(s.x() - pos.x()) <= GRIP + 2 and abs(s.y() - pos.y()) <= GRIP + 2:
                    return (e, i)
        return None

    def mousePressEvent(self, ev):
        self.setFocus()
        self.mouse = ev.position()
        if ev.button() == Qt.MouseButton.MiddleButton:
            if self.workspace_3d and (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.orbiting = True
                self.orbit_last = ev.position()
                self._orbit_pivot = self._orbit_pivot_point()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            else:
                self.panning = True
                self.pan_last = ev.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if ev.button() == Qt.MouseButton.RightButton:
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        view,_vn,_vr=self._view_at(ev.position())
        # A click-only axis selection may remain armed so TAB can start exact input.
        # Any later click that is not on a gizmo handle cancels that armed state first.
        if self._gizmo_drag is not None and self._gizmo_drag.get("armed") and not self._gizmo_drag.get("mouse_down"):
            probe=self._gizmo_hit(ev.position(),view=view)
            if probe is None:
                self.cancel_gizmo_drag()
        gh=self._gizmo_hit(ev.position(),view=view)
        if gh is not None:
            kind,constraint,origin=gh; originals=[e for e in self.selection if isinstance(e,Solid3D)]
            gd={"kind":kind,"constraint":constraint,"origin":origin,"start":QPointF(ev.position()),"view":view,
                "originals":originals,"current_solids":list(originals),"amount":0.0,"translation":(0.0,0.0,0.0),"numeric_entry":False,"numeric_buffer":"","mouse_down":True,"armed":False}
            if kind=="AXIS":
                gd["start_param"]=self._axis_drag_parameter(view,ev.position(),origin,constraint)
                if gd["start_param"] is None:return
            else:
                gd["start_world"]=self._plane_drag_point(view,ev.position(),origin,constraint)
                if gd["start_world"] is None:return
            self._gizmo_drag=gd;self.setCursor(Qt.CursorShape.ClosedHandCursor);return
        if self._viewcube_hit(ev.position()):
            return
        if self.workspace_3d and self.orbit_once:
            self.orbiting = True
            self.orbit_last = ev.position()
            self._orbit_pivot = self._orbit_pivot_point()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        self._retarget()
        self.click(ev.position(), bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier))

    def click(self, pos, shift=False):
        """左鍵點擊（測試也會直接呼叫）。"""
        self.mouse = QPointF(pos)
        view, _vn, _vr = self._view_at(self.mouse)
        w = self._screen_point(view, self.mouse)
        r = self.req
        if self.box_start is not None and self.box_wait:
            self._finish_box(pos, shift)
            return
        if r is None:
            g = self._grip_at(pos)
            if g is not None and not shift:
                self.grip_selection = list(self.selection)
                e, i = g
                self.start_command("GRIP_STRETCH", C.GRIP_STRETCH(self, e, i))
                self.cmd_name = "** 拉伸 **"
                self.promptChanged.emit(self.prompt_html())
                return
            e = self.pick_screen(self.mouse, view=view) if (self.workspace_3d or self.quad_view or view.orientation != "TOP") else (self.pick(w) if w is not None else None)
            if e is not None:
                if shift:
                    self.selection = [x for x in self.selection if x is not e]
                elif not any(x is e for x in self.selection):
                    self.selection.append(e)
                self.selectionChanged.emit()
                self.update()
            else:
                self.box_start = QPointF(pos)
                self.box_wait = False
            return
        if r.kind == "point":
            if self._uses_3d_input() and w is None:
                return
            self._retarget(); pt_value=self.cur_pt; self.temp_osnap=None; self._advance(pt_value,echo="")
        elif r.kind == "entity":
            e = self.pick_screen(self.mouse, types=r.types, view=view) if (self.workspace_3d or self.quad_view or view.orientation != "TOP") else (self.pick(w, types=r.types) if w is not None else None)
            if e is not None:
                self.entity_shift = bool(shift)
                self._advance((e, w), echo="")
            elif r.default == "point":
                self._advance((None, w), echo="")
        elif r.kind == "select":
            e = self.pick_screen(self.mouse, view=view) if (self.workspace_3d or self.quad_view or view.orientation != "TOP") else (self.pick(w) if w is not None else None)
            if e is not None:
                self._pend([e], remove=shift)
            else:
                self.box_start = QPointF(pos)
                self.box_wait = False

    def _finish_box(self, pos, shift=False):
        a, b = self.box_start, pos
        self.box_start = None
        self.box_wait = False
        if abs(a.x() - b.x()) < 2 or abs(a.y() - b.y()) < 2:
            self.update()
            return
        crossing = b.x() < a.x()
        view, _vn, _vr = self._view_at(QPointF((a.x()+b.x())/2,(a.y()+b.y())/2))
        if self.quad_view or view.orientation != "TOP":
            sr=(min(a.x(),b.x()),min(a.y(),b.y()),max(a.x(),b.x()),max(a.y(),b.y()))
            found=self.box_select_screen(sr,crossing,view=view)
            self.last_window=None
        else:
            p1, p2 = view.s2w(a.x(), a.y()), view.s2w(b.x(), b.y())
            rc = (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
            found = self.box_select(rc, crossing)
            self.last_window = rc if crossing else None
        if self.req is not None and self.req.kind == "select":
            self._pend(found, remove=shift)
        elif self.req is None:
            if shift:
                ids = {id(e) for e in found}
                self.selection = [e for e in self.selection if id(e) not in ids]
            else:
                ids = {id(e) for e in self.selection}
                self.selection += [e for e in found if id(e) not in ids]
            self.selectionChanged.emit()
        self.update()

    def mouseMoveEvent(self, ev):
        self.mouse = ev.position()
        self.inside = True
        if self._gizmo_drag is not None:
            gd=self._gizmo_drag
            # Click-selecting an axis leaves it armed for TAB numeric entry. Merely
            # moving the mouse after release must not move the solid.
            if not gd.get("mouse_down",False):
                self.update();return
            view=gd["view"];origin=gd["origin"];kind=gd["kind"];constraint=gd["constraint"]
            if kind=="AXIS":
                t=self._axis_drag_parameter(view,ev.position(),origin,constraint)
                if t is None:return
                amount=t-gd["start_param"];av=self._axis_world(constraint);tr=tuple(av[i]*amount for i in range(3));gd["amount"]=amount
            else:
                q=self._plane_drag_point(view,ev.position(),origin,constraint)
                if q is None:return
                s0=gd["start_world"];tr=(q[0]-s0[0],q[1]-s0[1],q[2]-s0[2])
                # Mathematically exact hard lock: remove the forbidden axis bit-for-bit.
                forbidden=({"XY":2,"XZ":1,"YZ":0})[constraint];tr=list(tr);tr[forbidden]=0.0;tr=tuple(tr)
            gd["translation"]=tr
            if not gd.get("numeric_entry"):
                self._gizmo_preview_translation(gd,tr)
            else:
                self.update()
            return
        if self.orbiting and self.orbit_last is not None:
            d = ev.position() - self.orbit_last
            self._orbit_by(d.x(), d.y())
            self.orbit_last = ev.position()
            return
        if self.panning and self.pan_last is not None:
            d = ev.position() - self.pan_last
            self.view.ox += d.x()
            self.view.oy += d.y()
            self.pan_last = ev.position()
            self.invalidate()
            return
        self.move_to(ev.position())

    def move_to(self, pos):
        self.mouse = QPointF(pos)
        self.inside = True
        self._retarget()
        r = self.req
        view, _vn, _vr = self._view_at(self.mouse)
        w = self._screen_point(view, self.mouse)
        self.hover_grip = self._grip_at(pos) if r is None else None
        if self.box_start is None and (r is None or r.kind in ("select", "entity")) and self.hover_grip is None:
            tp=r.types if r is not None and r.kind == "entity" else None
            self.hover = self.pick_screen(self.mouse, types=tp, view=view) if (self.workspace_3d or self.quad_view or view.orientation != "TOP") else (self.pick(w, types=tp) if w is not None else None)
        else:
            self.hover = None
        self.update()

    def mouseReleaseEvent(self, ev):
        self.mouse = ev.position()
        if ev.button() == Qt.MouseButton.LeftButton and self._gizmo_drag is not None:
            gd=self._gizmo_drag
            gd["mouse_down"]=False
            # If TAB numeric entry is active, releasing the mouse must not commit the
            # transient preview. Keep the axis constraint alive until Enter/Esc.
            if gd.get("numeric_entry"):
                gd["armed"]=True
                self._restore_cursor();self.update();return
            # A simple click on an axis is an explicit constraint selection. Keep it
            # armed so the natural CAD workflow "click Z → TAB → -20 → Enter" works.
            tr=gd.get("translation",(0.0,0.0,0.0))
            mag=math.sqrt(sum(float(v)*float(v) for v in tr))
            if gd.get("kind")=="AXIS" and mag<=1e-9:
                gd["armed"]=True
                self._restore_cursor()
                self.history.emit("<%s 軸已選取；按 TAB 可輸入精確距離。>" % gd.get("constraint","?"))
                self.update();return
            self._finish_gizmo_translation();return
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.panning = False
            self.pan_last = None
            self.orbiting = False
            self.orbit_last = None
            self._orbit_pivot = None
            self._restore_cursor()
            self.invalidate()  # redraw final camera at full-quality LOD
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            if self.orbiting:
                self.orbiting = False
                self.orbit_last = None
                self._orbit_pivot = None
                self.orbit_once = False
                self._restore_cursor()
                self.invalidate()  # redraw final camera at full-quality LOD
                return
            self.release(ev.position(), bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier))

    def release(self, pos, shift=False):
        """左鍵放開：拖曳框選就結束；只是點一下則等第二次點擊。"""
        if self.box_start is not None and not self.box_wait:
            d = QPointF(pos) - self.box_start
            if abs(d.x()) > 4 or abs(d.y()) > 4:
                self._finish_box(QPointF(pos), shift)
            else:
                self.box_wait = True

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.zoom_extents()
        elif ev.button() == Qt.MouseButton.LeftButton and self.gen is None:
            self.box_start = None
            view,_vn,_vr=self._view_at(ev.position());w=self._screen_point(view,ev.position())
            e=self.pick_screen(ev.position(),view=view) if (self.workspace_3d or self.quad_view or view.orientation!="TOP") else (self.pick(w) if w is not None else None)
            if e is not None:
                self.editRequested.emit(e)

    def wheelEvent(self, ev):
        """Zoom with both classic wheel and Linux/Wayland smooth-scroll events.

        On Windows a mouse wheel normally supplies ``angleDelta()`` in 120-unit
        notches.  On Linux, especially under Wayland/libinput and with touchpads,
        Qt can instead report only ``pixelDelta()``.  The old implementation
        ignored those events completely, which made viewport zoom look broken.
        """
        angle_y = float(ev.angleDelta().y())
        pixel_y = float(ev.pixelDelta().y())

        if angle_y:
            steps = angle_y / 120.0
            self._wheel_pixel_accum = 0.0
        elif pixel_y:
            # Smooth scrolling can arrive as many tiny pixel deltas.  Keep them
            # proportional instead of waiting for a full 120-unit wheel notch.
            # 40 px ~= one conventional wheel step gives a natural CAD feel.
            steps = pixel_y / 40.0
        else:
            ev.ignore()
            return

        # Clamp a single event so a driver spike cannot throw the model far away.
        steps = max(-4.0, min(4.0, steps))
        factor = 1.2 ** steps
        if abs(factor - 1.0) < 1e-9:
            ev.ignore()
            return

        if self.quad_view and self.workspace_3d:
            _q, name, _r = self._view_at(ev.position())
            z = float(self._quad_zoom.get(name, 1.0)) * factor
            self._quad_zoom[name] = max(0.08, min(80.0, z))
            self.quad_active = name
            self.invalidate()
            self._retarget()
            ev.accept()
            return

        self.zoom_factor(factor, at=ev.position())
        self._retarget()
        ev.accept()

    def enterEvent(self, ev):
        self.inside = True
        self.update()

    def leaveEvent(self, ev):
        self.inside = False
        self.hover = None
        self.update()

    def _set_temp_osnap(self, mode):
        self.temp_osnap = mode
        if mode == "NONE":
            self.msg("暫時關閉物件鎖點（僅下一點）")
        elif mode:
            self.msg("暫時物件鎖點: %s（僅下一點）" % SNAP_NAMES.get(mode, mode))
        self._retarget()
        self.update()

    def contextMenuEvent(self, ev):
        r = self.req
        if (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier) and r is not None and r.kind == "point":
            m = QMenu(self)
            m.addAction("無 (關閉單次鎖點)", lambda: self._set_temp_osnap("NONE"))
            m.addSeparator()
            for k in SNAP_ORDER:
                m.addAction(SNAP_NAMES[k], lambda _=False, k=k: self._set_temp_osnap(k))
            m.exec(ev.globalPos())
            return
        if r is not None and r.kind == "select":
            self.enter()
            return
        m = QMenu(self)
        if r is not None:
            m.addAction("輸入 (Enter)", self.enter)
            m.addAction("取消 (Esc)", self.cancel)
            if r.keywords:
                m.addSeparator()
                for k, n in r.keywords:
                    m.addAction("%s (%s)" % (n, k), lambda k=k: self.click_keyword(k))
        else:
            m.addAction("重複上一個指令", lambda: self.commandRequested.emit(""))
            m.addSeparator()
            if self.selection:
                for label, cmd in (("刪除", "ERASE"), ("移動", "MOVE"), ("複製選集", "COPY"), ("比例", "SCALE"),
                                   ("旋轉", "ROTATE"), ("選取類似物件", "SELECTSIMILAR")):
                    m.addAction(label, lambda cmd=cmd: self.commandRequested.emit(cmd))
                m.addAction("全部取消選取", lambda: self.cancel())
                m.addSeparator()
            m.addAction("剪下\tCtrl+X", lambda: self.commandRequested.emit("CUTCLIP"))
            m.addAction("複製\tCtrl+C", lambda: self.commandRequested.emit("COPYCLIP"))
            m.addAction("貼上\tCtrl+V", lambda: self.commandRequested.emit("PASTECLIP"))
            m.addSeparator()
            m.addAction("退回\tCtrl+Z", lambda: self.commandRequested.emit("U"))
            m.addAction("重做\tCtrl+Y", lambda: self.commandRequested.emit("REDO"))
            m.addSeparator()
            m.addAction("縮放實際範圍", self.zoom_extents)
            m.addAction("性質\tCtrl+1", lambda: self.commandRequested.emit("PROPERTIES"))
        m.addSeparator()
        m.addAction("縮放實際範圍" if r is not None else "上一個視圖",
                    self.zoom_extents if r is not None else self.zoom_prev)
        m.exec(ev.globalPos())

    def _toggle_dyn_field(self, step=1):
        if self.req is None or self.req.kind != "point" or self.req.base is None or self._uses_3d_input():
            return False
        self._dyn_field = "ANGLE" if self._dyn_field == "DIST" else "DIST"
        self.history.emit("<動態輸入：%s　TAB 切換 距離 / 角度>" % ("角度" if self._dyn_field=="ANGLE" else "距離"))
        self.update()
        return True

    def focusNextPrevChild(self, next):
        # Qt normally consumes TAB for focus traversal before keyPressEvent.  Gizmo
        # exact-entry must therefore intercept it here as well.
        if self._gizmo_drag is not None:
            if self.begin_gizmo_numeric():
                return True
        if self._toggle_dyn_field(1 if next else -1):
            return True
        return super().focusNextPrevChild(next)

    def keyPressEvent(self, ev):
        k = ev.key()
        # Gizmo exact-distance entry is handled locally so it never depends on
        # whether the command line happens to own keyboard focus.
        if self.gizmo_numeric_active():
            gd=self._gizmo_drag
            if k == Qt.Key.Key_Escape:
                self.cancel_gizmo_drag();return
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                buf=gd.get("numeric_buffer","")
                if buf.strip(): self.accept_gizmo_numeric(buf)
                else: self.history.emit("<請輸入距離，例如 -20。>")
                return
            if k == Qt.Key.Key_Backspace:
                gd["numeric_buffer"]=gd.get("numeric_buffer","")[:-1];self.update();return
            if k == Qt.Key.Key_Tab:
                return
            t=ev.text()
            if t and all(ch in "+-0123456789.eE" for ch in t):
                gd["numeric_buffer"]=gd.get("numeric_buffer","")+t
                self.update();return
            # Ignore other printable input while exact entry owns the keyboard.
            if t and t.isprintable(): return
        if k == Qt.Key.Key_Escape:
            self.cancel()
            return
        if k == Qt.Key.Key_Delete:
            if self.gen is None and self.selection:
                self.commandRequested.emit("ERASE")
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or (k == Qt.Key.Key_Space and (self.req is None or self.req.kind != "text")):
            if self.req is not None:
                self.enter()
            else:
                self.commandRequested.emit("")
            return
        if k == Qt.Key.Key_Tab:
            if self._gizmo_drag is not None:
                if self.begin_gizmo_numeric():return
            if self._toggle_dyn_field(-1 if (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1):return
        t = ev.text()
        if t and t.isprintable() and not (ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            self.keyTyped.emit(t)
            return
        super().keyPressEvent(ev)


def is_point(v):
    return isinstance(v, tuple) and len(v) in (2,3) and all(isinstance(x, (int, float)) for x in v)


def parse_number(s):
    s = s.strip()
    if s[-1:] in ("x", "X"):
        s = s[:-1]
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None
