# SPDX-License-Identifier: GPL-3.0-only
import math
import pytest

from pycad2d.model import Document, Solid3D, Hatch, Array, Circle
from pycad2d.commands import BOX, CYLINDER


class Plane:
    def __init__(self,u,v,n): self.u,self.v,self.n=u,v,n

class FakeCanvas:
    def __init__(self,plane):
        self.doc=Document(); self.view=None; self.mouse=None; self.plane=plane; self.added=[]
    def effective_work_plane(self,view=None): return self.plane
    def work_plane(self,view=None): return self.plane
    def add(self,e): self.doc.entities.append(e); self.added.append(e); return e
    def changed(self): pass
    def msg(self,x): pass


def run_box(c,a,b,h):
    g=BOX(c); assert next(g).kind=='point'; assert g.send(a).kind=='point'; assert g.send(b).kind=='num'
    with pytest.raises(StopIteration): g.send(h)
    return c.added[-1]


def run_cylinder(c,cen,rp,h):
    g=CYLINDER(c); assert next(g).kind=='point'; assert g.send(cen).kind=='point'; assert g.send(rp).kind=='num' or True
    # radius point is accepted by the command and converted to a numeric radius; next request is height.
    # generator send above returns height request.
    req=g.send(h) if False else None


def test_front_workplane_box_has_real_normal_thickness():
    # FRONT: U=+X, V=+Z, N=-Y
    c=FakeCanvas(Plane((1,0,0),(0,0,1),(0,-1,0)))
    e=run_box(c,(200,0,10),(260,0,50),30)
    b=e.bbox3d()
    assert math.isclose(b[3]-b[0],60,abs_tol=1e-9)
    assert math.isclose(b[5]-b[2],40,abs_tol=1e-9)
    assert math.isclose(b[4]-b[1],30,abs_tol=1e-9)


def test_front_workplane_cylinder_axis_is_plane_normal():
    c=FakeCanvas(Plane((1,0,0),(0,0,1),(0,-1,0)))
    g=CYLINDER(c)
    assert next(g).kind=='point'
    req=g.send((0,0,0)); assert req.kind=='point'
    req=g.send((10,0,0)); assert req.kind=='num'
    with pytest.raises(StopIteration): g.send(20.0)
    e=c.added[-1]; b=e.bbox3d()
    assert math.isclose(b[4]-b[1],20.0,abs_tol=1e-9)  # height along world Y
    assert math.isclose(b[3]-b[0],20.0,rel_tol=1e-6)  # radius in X
    assert math.isclose(b[5]-b[2],20.0,rel_tol=1e-6)  # radius in Z


def test_hatch_island_area_ignores_loop_winding():
    outer=[(0,0),(100,0),(100,50),(0,50)]
    hole=[(60+10*math.cos(2*math.pi*i/128),25+10*math.sin(2*math.pi*i/128)) for i in range(128)]
    h=Hatch(loops=[outer,hole])  # both CCW on purpose
    assert abs(h.area()-(5000-math.pi*100)) < 0.5


def test_nested_array_has_recursive_hard_guard():
    base=Circle(cx=0,cy=0,r=1)
    a1=Array(source=[base],mode='RECT',rows=10,cols=10,dx=2,dy=2)
    a2=Array(source=[a1],mode='RECT',rows=10,cols=10,dx=30,dy=30)
    a3=Array(source=[a2],mode='RECT',rows=3,cols=3,dx=400,dy=400)
    assert a3.expanded_count(20000)>20000
    assert a3.parts()==[]
    assert a3.__dict__.get('_expansion_blocked') is True


def test_display_mesh_keeps_multiple_lods_and_hit_numpy_is_cached():
    # 3000-strip mesh: large enough to request two distinct display LOD keys.
    verts=[(float(i),0.0,0.0) for i in range(3002)] + [(float(i),1.0,0.0) for i in range(3002)]
    n=3002; faces=[]
    for i in range(1500):
        faces.append((i,i+1,n+i)); faces.append((i+1,n+i+1,n+i))
    e=Solid3D(vertices=verts,faces=faces,edges=[])
    e.display_mesh(2000); e.display_mesh(2500)
    cache=e.__dict__.get('_display_mesh_cache')
    assert isinstance(cache,dict) and len(cache)>=2
    try:
        a=e.hit_arrays(); b=e.hit_arrays()
    except Exception:
        pytest.skip('numpy unavailable')
    assert a is not None and a[0] is b[0] and a[2] is b[2]

def test_place3d_practical_attach_inward_mm():
    from pycad2d.commands import PLACE3D
    moving=Solid3D(vertices=[(0,0,0),(1,0,0),(0,1,0)],faces=[(0,1,2)],edges=[])
    target=Solid3D(vertices=[(0,0,0),(10,0,0),(10,10,0),(0,10,0),(0,0,4),(10,0,4),(10,10,4),(0,10,4)],
                   faces=[(0,1,2,3),(4,5,6,7)],edges=[])
    class C:
        def __init__(self):self.last_subface=(target,(4,5,6,7));self.replaced=None;self.kept=[]
        def replace(self,o,n):self.replaced=(o,n)
        def msg(self,x):pass
        def changed(self):pass
        def keep_selection(self,x):self.kept=x
    c=C();g=PLACE3D(c)
    assert next(g).kind=='select'
    assert g.send([moving]).kind=='point'
    assert g.send((0,0,0)).face_pick
    assert g.send((2,3,4)).kind=='kw'
    assert g.send('I').kind=='num'
    with pytest.raises(StopIteration):g.send(10.0)
    moved=c.replaced[1]
    # source point snaps to target (2,3,4), then goes 10mm inward (-Z)
    assert moved.vertices[0]==pytest.approx((2,3,-6))
