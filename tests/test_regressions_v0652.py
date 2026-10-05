# SPDX-License-Identifier: GPL-3.0-only
"""v0.6.5.3 external 3D import/viewer stability regressions."""
import math
import os
import tempfile

import pytest

from pycad2d import io_utils as IO
from pycad2d.model import Solid3D


def test_mesh_sanitizer_drops_invalid_and_degenerate_faces():
    s = IO._solid_from_mesh(
        [(0,0,0),(1,0,0),(0,1,0),(float('nan'),0,0)],
        [(0,1,2),(0,0,1),(0,3,1),(0,1,99),(2,1,0)],
        'TEST')
    assert len(s.vertices) == 3
    assert len(s.faces) == 1
    assert all(all(math.isfinite(c) for c in v) for v in s.vertices)


def test_large_mesh_builds_bounded_display_lod_without_changing_source():
    n=230
    vertices=[(float(x),float(y),0.0) for y in range(n) for x in range(n)]
    faces=[]
    for y in range(n-1):
        for x in range(n-1):
            a=y*n+x;b=a+1;c=a+n;d=c+1
            faces.extend(((a,b,d),(a,d,c)))
    s=Solid3D(vertices=vertices,faces=faces,edges=[])
    original=len(s.faces)
    vv,ff,ee=s.display_mesh(30000)
    assert len(s.faces)==original
    assert 0 < len(ff) <= 30000
    assert len(ee) <= 10000
    assert all(all(math.isfinite(c) for c in v) for v in vv)


def test_ascii_stl_welds_duplicate_vertices():
    text='''solid t\nfacet normal 0 0 1\n outer loop\n  vertex 0 0 0\n  vertex 1 0 0\n  vertex 0 1 0\n endloop\nendfacet\nfacet normal 0 0 1\n outer loop\n  vertex 1 0 0\n  vertex 1 1 0\n  vertex 0 1 0\n endloop\nendfacet\nendsolid t\n'''
    fd,path=tempfile.mkstemp(suffix='.stl');os.close(fd)
    try:
        with open(path,'w',encoding='ascii') as f:f.write(text)
        e=IO.import_stl(path)[0]
        assert len(e.vertices) == 4
        assert len(e.faces) == 2
    finally:
        os.unlink(path)


def test_step_keeps_exact_brep_and_bounded_display_mesh():
    cq=pytest.importorskip('cadquery')
    shape=cq.Workplane('XY').cylinder(50,20).edges().fillet(2)
    fd,path=tempfile.mkstemp(suffix='.step');os.close(fd)
    try:
        cq.exporters.export(shape,path,exportType='STEP')
        e=IO.import_step(path)[0]
        assert e.brep_b64
        assert 0 < len(e.faces) <= 70000
        vv,ff,ee=e.display_mesh(30000)
        assert len(ff) <= 30000
    finally:
        os.unlink(path)
