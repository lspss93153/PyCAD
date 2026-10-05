# SPDX-License-Identifier: GPL-3.0-only
"""v0.6.5 regression tests for stability/fidelity work.

These deliberately exercise existing features only; v0.6.5 is a correctness release,
not a feature release.
"""
import math
import os
import tempfile

import pytest

from pycad2d import io_utils as IO
from pycad2d.model import Array, Document, Hatch, Line, Polyline, Solid3D


def test_array_grips_follow_local_rect_axes():
    arr = Array(source=[Line(x1=0, y1=0, x2=2, y2=0)], mode="rect", rows=3, cols=4,
                col_vec=(0.0, 10.0), row_vec=(-20.0, 0.0))
    g = arr.grips()
    # source centre is (1,0); column and row handles lie on the actual rotated vectors
    assert g[0] == pytest.approx((1.0, 0.0))
    assert g[1] == pytest.approx((1.0, 30.0))
    assert g[2] == pytest.approx((-39.0, 0.0))
    moved = arr.grip_moved(1, (1.0, 60.0))
    assert moved.col_vec == pytest.approx((0.0, 20.0))
    assert moved.row_vec == pytest.approx((-20.0, 0.0))


def test_large_rect_array_hit_test_does_not_expand_every_part():
    d = Document()
    arr = Array(source=[Line(x1=0, y1=0, x2=1, y2=0)], mode="rect", rows=40, cols=40,
                col_vec=(5.0, 0.0), row_vec=(0.0, 5.0))
    # A hit near row/column 20 should be found parametrically.  Large-array picking
    # must not populate the full parts cache on every mouse move.
    dist = d.hit_dist(arr, (100.5, 100.0))
    assert dist < 1e-6
    assert "_parts_cache" not in arr.__dict__


def test_dxf_truecolor_and_polyline_width_roundtrip():
    pytest.importorskip("ezdxf")
    d = Document()
    d.entities = [Polyline(pts=[(0, 0, 0), (10, 0, 0), (10, 10, 0)],
                           truecolor=0x123456, const_width=2.5,
                           widths=[(1.0, 2.0), (2.0, 3.0), (3.0, 4.0)])]
    with tempfile.TemporaryDirectory() as td:
        fn = os.path.join(td, "fidelity.dxf")
        IO.export_dxf_2010(fn, d)
        back = IO.import_dxf(fn)
    p = next(e for e in back.entities if isinstance(e, Polyline))
    assert p.truecolor == 0x123456
    assert p.const_width == pytest.approx(2.5)
    assert p.widths == pytest.approx([(1, 2), (2, 3), (3, 4)])


def test_hatch_arc_boundary_roundtrip_stays_arc():
    pytest.importorskip("ezdxf")
    d = Document()
    d.entities = [Hatch(loops=[[(10, 0), (0, 10), (-10, 0), (0, -10)]],
                        loop_prims=[[('A', 0, 0, 10, 0, 360)]], pattern="ANSI31")]
    with tempfile.TemporaryDirectory() as td:
        fn = os.path.join(td, "hatch.dxf")
        IO.export_dxf_2010(fn, d)
        back = IO.import_dxf(fn)
    h = next(e for e in back.entities if isinstance(e, Hatch))
    assert h.loop_prims
    assert h.loop_prims[0][0][0] == "A"
    assert h.loop_prims[0][0][3] == pytest.approx(10.0)


def test_oda_launch_strips_pycad_qt_environment(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(IO, "find_oda", lambda: "/fake/ODAFileConverter")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/bad/plugins")
    monkeypatch.setenv("QT_QPA_PLATFORM_PLUGIN_PATH", "/bad/platforms")
    monkeypatch.setenv("QML2_IMPORT_PATH", "/bad/qml")

    class Result:
        returncode = 0

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(IO.subprocess, "run", fake_run)
    IO._oda(str(tmp_path / "in"), str(tmp_path / "out"), "ACAD2018", "DXF", "*.dwg")
    env = captured["env"]
    assert "QT_QPA_PLATFORM" not in env
    assert "QT_PLUGIN_PATH" not in env
    assert "QT_QPA_PLATFORM_PLUGIN_PATH" not in env
    assert "QML2_IMPORT_PATH" not in env
    assert captured["timeout"] == 300


def test_wedge_exact_step_is_not_mesh_only_when_cadquery_available():
    cq = pytest.importorskip("cadquery")
    from pycad2d.commands import _cq_polyhedron
    from pycad2d.io_utils import _shape_to_brep_b64

    verts = [(0,0,0),(10,0,0),(10,5,0),(0,5,0),(0,0,8),(0,5,8)]
    faces = [(0,3,2,1),(0,4,5,3),(0,1,4),(3,5,2),(1,2,5,4)]
    sh = _cq_polyhedron(verts, faces)
    assert sh is not None and sh.isValid()
    assert len(_shape_to_brep_b64(sh)) > 100


def test_stl_import_merges_duplicate_triangle_vertices():
    pytest.importorskip("trimesh")
    text = """solid x
 facet normal 0 0 1
  outer loop
   vertex 0 0 0
   vertex 1 0 0
   vertex 1 1 0
  endloop
 endfacet
 facet normal 0 0 1
  outer loop
   vertex 0 0 0
   vertex 1 1 0
   vertex 0 1 0
  endloop
 endfacet
endsolid x
"""
    with tempfile.TemporaryDirectory() as td:
        fn = os.path.join(td, "square.stl")
        with open(fn, "w", encoding="ascii") as f:
            f.write(text)
        out = IO.import_stl(fn)
    s = out[0]
    assert isinstance(s, Solid3D)
    assert len(s.vertices) == 4
    assert len(s.faces) == 2


def test_associative_hatch_refreshes_from_stable_boundary_uid():
    from pycad2d.model import Circle
    d = Document()
    c = Circle(cx=0, cy=0, r=10)
    outline = __import__('pycad2d.edit_ops', fromlist=['closed_outline']).closed_outline(c)
    h = Hatch(loops=[outline], loop_prims=[[tuple(pr) for pr in c.prims()]], boundary_uids=[[c.uid]])
    d.entities = [c, h]
    from pycad2d import geometry as G
    moved = c.transformed(G.m_translate(20, 5))
    # A real replacement retains c.uid; emulate Canvas replace in a non-GUI test.
    moved = moved.clone(uid=c.uid)
    d.entities[0] = moved
    assert d.refresh_associative_hatches({c.uid})
    hh = next(e for e in d.entities if isinstance(e, Hatch))
    assert hh.loop_prims[0][0][0] == 'A'
    assert hh.loop_prims[0][0][1] == pytest.approx(20.0)
    assert hh.loop_prims[0][0][2] == pytest.approx(5.0)


def test_project_roundtrip_preserves_entity_ids_and_hatch_links():
    from pycad2d.model import Circle
    d = Document(); c = Circle(cx=1, cy=2, r=3)
    h = Hatch(loops=[[(4,2),(1,5),(-2,2),(1,-1)]], loop_prims=[[tuple(pr) for pr in c.prims()]], boundary_uids=[[c.uid]])
    d.entities = [c, h]
    back = Document.from_json(d.to_json())
    bc = next(e for e in back.entities if isinstance(e, Circle)); bh = next(e for e in back.entities if isinstance(e, Hatch))
    assert bc.uid == c.uid
    assert bh.boundary_uids == [[c.uid]]


def test_rect_array_dxf_roundtrip_stays_single_array():
    pytest.importorskip("ezdxf")
    from pycad2d import geometry as G
    a = Array(source=[Line(x1=1,y1=2,x2=5,y2=2)], mode="RECT", rows=3, cols=4,
              col_vec=(8,0), row_vec=(0,6), dx=8, dy=6)
    a = a.transformed(G.m_rotate((0,0), 35))
    d=Document(); d.entities=[a]
    with tempfile.TemporaryDirectory() as td:
        fn=os.path.join(td,"array.dxf")
        IO.export_dxf_2010(fn,d)
        back=IO.import_dxf(fn)
    assert len(back.entities)==1
    b=back.entities[0]
    assert isinstance(b,Array) and b.rows==3 and b.cols==4
    assert b.col_vec == pytest.approx(a.col_vec)
    assert b.row_vec == pytest.approx(a.row_vec)
    assert back.bbox(b) == pytest.approx(a.bbox())


def test_step_import_unit_scale_keeps_exact_brep():
    cq=pytest.importorskip("cadquery")
    with tempfile.TemporaryDirectory() as td:
        fn=os.path.join(td,"unit.step")
        cq.exporters.export(cq.Workplane("XY").box(10,20,30).val(),fn,exportType="STEP")
        out=IO.import_step(fn,scale=0.1)
    assert out and out[0].brep_b64
    b=out[0].bbox3d()
    assert (b[3]-b[0],b[4]-b[1],b[5]-b[2]) == pytest.approx((1,2,3),abs=1e-5)


def test_rect_array_r12_roundtrip_stays_single_array():
    from pycad2d import geometry as G
    a=Array(source=[Line(x1=1,y1=2,x2=5,y2=2)],mode="RECT",rows=2,cols=3,
            col_vec=(7,0),row_vec=(0,5),dx=7,dy=5).transformed(G.m_rotate((0,0),25))
    d=Document();d.entities=[a]
    with tempfile.TemporaryDirectory() as td:
        fn=os.path.join(td,"array_r12.dxf")
        IO.export_dxf_r12(fn,d)
        back=IO.import_dxf(fn)
    assert len(back.entities)==1 and isinstance(back.entities[0],Array)
    assert back.entities[0].rows==2 and back.entities[0].cols==3
    assert back.bbox(back.entities[0]) == pytest.approx(a.bbox())
