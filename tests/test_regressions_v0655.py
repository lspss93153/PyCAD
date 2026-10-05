# SPDX-License-Identifier: GPL-3.0-only
"""v0.6.5.5 WorkPlane / 3D correctness regressions."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from pycad2d.canvas import CadCanvas
from pycad2d.model import Solid3D

app = QApplication.instance() or QApplication([])


def make_canvas():
    c = CadCanvas()
    c.resize(800, 600)
    c.workspace_3d = True
    c.cmd_name = "BOX"
    c.view.w, c.view.h = 800, 600
    return c


def near(a, b, tol=1e-7):
    return all(abs(float(x)-float(y)) <= tol for x, y in zip(a, b))


def test_wcs_stays_world_xy_in_front_and_bottom_views():
    c = make_canvas()
    c.set_ucs_mode("WCS")
    c.view.set_orientation("FRONT")
    assert near(c.parse_point("10,20"), (10, 20, 0))
    # Mouse ray is parallel to WCS XY in FRONT: reject instead of jumping to origin.
    assert c.ray_plane(c.view, QPointF(400, 300), c.work_plane(c.view)) is None

    c.view.set_orientation("BOTTOM")
    p = c.work_plane(c.view)
    assert near(p.u, (1, 0, 0)) and near(p.v, (0, 1, 0))
    assert near(p.n, (0, 0, -1))  # normal faces the user
    assert near(c.parse_point("10,20"), (10, 20, 0))


def test_front_ucs_typed_coordinates_use_local_uv():
    c = make_canvas()
    c.set_ucs_mode("FRONT")
    c.view.set_orientation("FRONT")
    assert near(c.parse_point("10,20"), (10, 0, 20))
    base = (5, 0, 30)
    assert near(c.parse_point("@0,50", base), (5, 0, 80))
    assert near(c.parse_point("@10,20,3", base), (15, -3, 50))


def test_solid3d_fake_xy_grips_are_disabled():
    s = Solid3D(vertices=[(0,0,0),(1,0,0),(0,1,0)], edges=[(0,1),(1,2),(2,0)], faces=[(0,1,2)])
    assert s.grips() == []
