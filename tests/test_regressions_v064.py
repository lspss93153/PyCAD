# SPDX-License-Identifier: GPL-3.0-only
"""v0.6.4 correctness regressions that do not require a GUI."""
import math
import os
import tempfile
import pytest
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pycad2d.model import Array, Circle, Document, Line, Polyline, Solid3D
from pycad2d import geometry as G
from pycad2d.edit_ops import join_entities, offset_entity
from pycad2d import io_utils as IO


def near(a, b, tol=1e-6):
    return abs(a-b) <= tol


def test_rect_array_transform_preserves_local_spacing():
    a = Array(source=[Line(x1=0,y1=0,x2=1,y2=0)], mode="rect", rows=2, cols=2,
              col_vec=(10.0,0.0), row_vec=(0.0,20.0))
    r = a.transformed(G.m_rotate((0,0), 90))
    assert near(r.col_vec[0], 0) and near(r.col_vec[1], 10)
    assert near(r.row_vec[0], -20) and near(r.row_vec[1], 0)
    s = a.transformed(G.m_scale((0,0), 2, 2))
    assert s.col_vec == pytest.approx((20,0))
    assert s.row_vec == pytest.approx((0,40))
    m = a.transformed(G.m_scale((0,0), -1, 1))
    assert m.col_vec == pytest.approx((-10,0))


def test_polar_array_mirror_reverses_direction():
    a = Array(source=[Line(x1=1,y1=0,x2=2,y2=0)], mode="polar", count=4, fill=180)
    m = a.transformed(G.m_scale((0,0), -1, 1))
    assert m.fill == pytest.approx(-180)


def test_join_collinear_lines_returns_line():
    new, used = join_entities([Line(x1=0,y1=0,x2=5,y2=0), Line(x1=5,y1=0,x2=10,y2=0)])
    assert len(new) == 1
    out = new[0]
    assert isinstance(out, Line)
    assert {(out.x1,out.y1),(out.x2,out.y2)} == {(0,0),(10,0)}


def test_too_large_inward_offset_is_rejected():
    p = Polyline(pts=[(0,0,0),(100,0,0),(100,60,0),(0,60,0)], closed=True)
    # side point at the centre means inward; 40 is larger than half the short side.
    out = offset_entity(p, 40, (50,30))
    assert out is None


def test_vrml_multi_shape_roundtrip():
    d=Document()
    d.entities=[
        Solid3D(vertices=[(0,0,0),(1,0,0),(0,1,0)], faces=[(0,1,2)], edges=[(0,1),(1,2),(2,0)], shape="A"),
        Solid3D(vertices=[(10,0,0),(11,0,0),(10,1,0)], faces=[(0,1,2)], edges=[(0,1),(1,2),(2,0)], shape="B"),
    ]
    with tempfile.TemporaryDirectory() as td:
        fn=os.path.join(td,"x.wrl")
        IO.export_wrl(fn,d)
        back=IO.import_wrl(fn)
        assert len([e for e in back if isinstance(e,Solid3D)]) == 2


def test_exact_step_roundtrip_when_cadquery_available():
    pytest.importorskip("cadquery")
    import cadquery as cq
    from pycad2d.commands import _cq_to_solid
    class Dummy:
        def __init__(self): self.doc=Document()
        def msg(self, _): pass
    s=_cq_to_solid(Dummy(), cq.Workplane("XY").box(10,20,30).val(), "BOX")
    assert s.brep_b64
    d=Document(); d.entities=[s]
    with tempfile.TemporaryDirectory() as td:
        fn=os.path.join(td,"box.step")
        IO.export_step(fn,d)
        assert os.path.getsize(fn) > 1000
        back=IO.import_step(fn)
        assert back and back[0].brep_b64
