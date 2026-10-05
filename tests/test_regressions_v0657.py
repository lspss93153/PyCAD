# SPDX-License-Identifier: GPL-3.0-only
from types import SimpleNamespace

from pycad2d.model import Solid3D
from pycad2d.commands import _face_frame_from_canvas, _translate_solid3d


def _box():
    v=[(0,0,0),(10,0,0),(10,8,0),(0,8,0),(0,0,4),(10,0,4),(10,8,4),(0,8,4)]
    # Top winding is intentionally arbitrary; placement must orient it outward.
    f=[(0,1,2,3),(4,5,6,7)]
    return Solid3D(vertices=v, faces=f, edges=[], shape='BOX')


def test_face_frame_orients_top_normal_outward():
    s=_box()
    c=SimpleNamespace(last_subface=(s,(4,5,6,7)))
    origin,u,v,n=_face_frame_from_canvas(c)
    assert origin == (5.0,4.0,4.0)
    assert n[2] > 0.999999
    assert abs(sum(u[i]*n[i] for i in range(3))) < 1e-12
    assert abs(sum(v[i]*n[i] for i in range(3))) < 1e-12


def test_negative_normal_offset_goes_into_top_face():
    s=_box(); c=SimpleNamespace(last_subface=(s,(4,5,6,7)))
    origin,u,v,n=_face_frame_from_canvas(c)
    p=tuple(origin[i] + n[i]*(-2.0) for i in range(3))
    assert abs(p[2]-2.0) < 1e-9


def test_translate_solid3d_keeps_exact_xyz_delta_without_brep():
    s=_box()
    q=_translate_solid3d(s,1.25,-3.5,7.0)
    assert q.vertices[0] == (1.25,-3.5,7.0)
    assert q.vertices[-1] == (1.25,4.5,11.0)


def test_place3d_point_anchor_and_negative_depth():
    from pycad2d.commands import PLACE3D
    moving=Solid3D(vertices=[(0,0,0),(1,0,0),(0,1,0)], faces=[(0,1,2)], edges=[])
    target=_box()
    class C:
        def __init__(self):
            self.last_subface=(target,(4,5,6,7)); self.replaced=None; self.messages=[]; self.kept=[]
        def replace(self,o,n): self.replaced=(o,n)
        def msg(self,x): self.messages.append(x)
        def changed(self): pass
        def keep_selection(self,x): self.kept=x
    c=C();g=PLACE3D(c)
    assert next(g).kind=='select'
    assert g.send([moving]).kind=='point'
    assert g.send((0.0,0.0,0.0)).face_pick is True
    # Pick top-face point at (2,3,4), then point-anchor mode, U=0,V=0,N=-1.
    assert g.send((2.0,3.0,4.0)).kind=='kw'
    assert g.send('P').kind=='num'
    assert g.send(0.0).kind=='num'
    assert g.send(0.0).kind=='num'
    try:g.send(-1.0)
    except StopIteration:pass
    assert c.replaced is not None
    new=c.replaced[1]
    assert new.vertices[0] == (2.0,3.0,3.0)
