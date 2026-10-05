# SPDX-License-Identifier: GPL-3.0-only
"""v0.6.5.3 imported 3D visual fidelity/stability regressions."""
import math
import pytest
from pycad2d.model import Solid3D, Document


def _parallel_grids(n=80, size=100.0, gap=0.01):
    v=[]; f=[]
    for z,flip in ((0.0,False),(gap,True)):
        base=len(v)
        for y in range(n):
            for x in range(n):
                v.append((size*x/(n-1),size*y/(n-1),z))
        for y in range(n-1):
            for x in range(n-1):
                a=base+y*n+x;b=a+1;c=a+n;d=c+1
                if flip:
                    f.extend(((a,d,b),(a,c,d)))
                else:
                    f.extend(((a,b,d),(a,d,c)))
    return v,f


def test_lod_does_not_weld_opposite_thin_wall_skins():
    v,f=_parallel_grids()
    s=Solid3D(vertices=v,faces=f,edges=[])
    vv,ff,_=s.display_mesh(3500)
    assert ff
    zs=[p[2] for p in vv]
    # Position-only clustering used to average these two skins into one surface.
    assert min(zs) <= 1e-6
    assert max(zs) >= 0.009


def test_imported_mesh_feature_edge_cache_prefers_crease_over_diagonal():
    from pycad2d.io_utils import _limited_edges
    # Two coplanar triangles form a square: the shared diagonal is tessellation only.
    v=[(0,0,0),(1,0,0),(1,1,0),(0,1,0)]
    f=[(0,1,2),(0,2,3)]
    e=_limited_edges(v,f,cap=100)
    assert (0,2) not in e and (2,0) not in e
    for q in ((0,1),(1,2),(2,3),(0,3)):
        assert q in e or (q[1],q[0]) in e


def test_clean_wireframe_hides_coplanar_triangle_diagonal():
    try:
        from pycad2d.render import Renderer, View
    except Exception as ex:
        pytest.skip(str(ex))
    s=Solid3D(vertices=[(0,0,0),(1,0,0),(1,1,0),(0,1,0)],
              faces=[(0,1,2),(0,2,3)],edges=[])
    r=Renderer(Document());v=View();v.set_orientation('SEISO')
    vv,ff,_=s.display_mesh(100)
    ed=r._feature_edges(s,vv,ff,v,silhouette=True,cap=100)
    assert (0,2) not in ed and (2,0) not in ed
