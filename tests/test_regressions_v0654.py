# SPDX-License-Identifier: GPL-3.0-only
"""v0.6.5.4 3D object-snap / transform stability regressions."""
import math
import pytest

from pycad2d.model import Solid3D
from pycad2d.io_utils import _shape_to_brep_b64


def _near(a,b,tol=1e-6):
    return all(abs(float(x)-float(y)) <= tol for x,y in zip(a,b))


def _box():
    v=[(0,0,0),(10,0,0),(10,8,0),(0,8,0),(0,0,6),(10,0,6),(10,8,6),(0,8,6)]
    e=[(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    f=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    return Solid3D(vertices=v,edges=e,faces=f,shape="BOX")


def test_mesh_solid_3d_snap_vertices_midpoints_face_centres():
    s=_box(); pts=s.snap_points3d()
    ends=[p for k,p in pts if k=="END"]
    mids=[p for k,p in pts if k=="MID"]
    cens=[p for k,p in pts if k=="CEN"]
    assert any(_near(p,(0,0,0)) for p in ends)
    assert any(_near(p,(5,0,0)) for p in mids)
    assert any(_near(p,(5,4,6)) for p in cens)  # top-face centre
    assert any(k=="GCE" and _near(p,(5,4,3)) for k,p in pts)


def test_exact_cylinder_exposes_true_cap_centres():
    cq=pytest.importorskip("cadquery")
    sh=cq.Workplane("XY").circle(7).extrude(20).val()
    # Deliberately coarse display mesh: the exact BREP must still provide true centres.
    s=Solid3D(vertices=[(7,0,0),(7,0,20)],edges=[(0,1)],faces=[],shape="CYLINDER",
              brep_b64=_shape_to_brep_b64(sh))
    pts=s.snap_points3d(); cens=[p for k,p in pts if k=="CEN"]
    assert any(_near(p,(0,0,0),1e-5) for p in cens)
    assert any(_near(p,(0,0,20),1e-5) for p in cens)
    assert any(k=="MID" and _near(p,(7,0,10),1e-5) for k,p in pts)


def test_3d_snap_cache_is_bounded_for_dense_mesh():
    # Many feature edges must not turn every mouse move into an O(all triangles) scan.
    n=8000
    v=[(float(i),0.0,float(i%7)) for i in range(n)]
    e=[(i,i+1) for i in range(n-1)]
    s=Solid3D(vertices=v,edges=e,faces=[],shape="STL")
    pts=s.snap_points3d(6000)
    assert len(pts) <= 6000
    assert s.snap_points3d(6000) is pts
