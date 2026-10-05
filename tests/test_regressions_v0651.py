# SPDX-License-Identifier: GPL-3.0-only
"""v0.6.5.1 hotfix regressions.

No new commands/features are introduced here; these tests lock down fixes for existing
3D interaction/display behavior.
"""
import math
from pathlib import Path

import pytest

from pycad2d import commands as C
from pycad2d.io_utils import _cq_shape_from_solid
from pycad2d.model import Document, Solid3D


class _MockCanvas:
    def __init__(self):
        self.doc = Document()
        self.added = []

    def add(self, e):
        self.doc.entities.append(e)
        self.added.append(e)
        return e

    def changed(self):
        pass


def _make_sphere(radius=10.0, center=(0.0, 0.0, 0.0)):
    c = _MockCanvas()
    g = C.SPHERE(c)
    assert next(g).kind == "point"
    assert g.send(center).kind == "point"
    try:
        g.send(float(radius))
    except StopIteration:
        pass
    assert len(c.added) == 1
    return c.added[0]


def test_sphere_display_mesh_is_full_not_hemisphere():
    s = _make_sphere(10.0)
    assert isinstance(s, Solid3D)
    b = s.bbox3d()
    assert b == pytest.approx((-10, -10, -10, 10, 10, 10), abs=1e-8)
    # Keep the compact native UV display mesh instead of replacing it with a huge OCC mesh.
    assert len(s.vertices) == 482
    assert len(s.faces) == 512


def test_sphere_exact_brep_is_full_sphere_when_cadquery_available():
    pytest.importorskip("cadquery")
    s = _make_sphere(10.0)
    assert s.brep_b64
    sh = _cq_shape_from_solid(s, 1.0)
    bb = sh.BoundingBox()
    assert (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax) == pytest.approx(
        (-10, -10, -10, 10, 10, 10), abs=1e-7
    )
    assert sh.Volume() == pytest.approx(4.0 / 3.0 * math.pi * 10.0**3, rel=1e-7)


def test_canvas_xyz_cursor_uses_3d_projection_in_source():
    # PySide6 is optional in the headless build environment, so this regression checks
    # the exact source path that previously called View.w2s(x,y) with an XYZ tuple and
    # caused paintEvent to fail while the native cursor was hidden.
    src = Path(__file__).resolve().parents[1].joinpath("pycad2d", "canvas.py").read_text(encoding="utf-8")
    assert "def _project_point(view, q):" in src
    assert "view.project3(float(q[0]), float(q[1]), float(q[2]))" in src
    assert "p.drawLine(self._project_point(v, r.base), self._project_point(v, self.cur_pt))" in src
    assert "Qt.CursorShape.CrossCursor if self.workspace_3d" in src


def test_wireframe_styles_have_distinct_edge_paths_in_source():
    src = Path(__file__).resolve().parents[1].joinpath("pycad2d", "render.py").read_text(encoding="utf-8")
    assert "def _solid_wire_edges(self, e, style, view):" in src
    assert 'st=str(style).upper()' in src
    assert 'if st=="3DWIREFRAME":' in src
    assert 'self._feature_edges(e,vv,ff,view' in src
    assert 'self._display_mesh(e,limit)' in src
