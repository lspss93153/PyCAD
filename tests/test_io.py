# SPDX-License-Identifier: GPL-3.0-only
"""DXF 相容性測試：用 ezdxf 產生「真正的」AutoCAD 2010 / R12 DXF 來驗證匯入，
再把匯出的檔案交給 ezdxf 稽核。  執行： python tests/test_io.py"""
import os
import sys
import math
import tempfile
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pycad2d.model import *
from pycad2d import geometry as G
from pycad2d import io_utils as IO

try:
    import ezdxf
except ImportError:
    print("略過：沒有安裝 ezdxf")
    sys.exit(0)

TMP = tempfile.mkdtemp(prefix="pycad_test_")
N = 0


def ok(cond, name):
    global N
    if not cond:
        raise AssertionError("FAIL: " + name)
    N += 1


def near(a, b, t=1e-6):
    return abs(a - b) <= t


def make_reference(version):
    d = ezdxf.new(version, setup=True)
    d.layers.add("牆", color=1, linetype="CENTER")
    d.layers.add("HIDDEN_OFF", color=3).off()
    m = d.modelspace()
    m.add_line((0, 0), (100, 0), dxfattribs={"layer": "牆"})
    m.add_circle((50, 50), 20, dxfattribs={"color": 5})
    m.add_arc((0, 0), 10, 30, 120)
    m.add_point((5, 5))
    m.add_text("單行 TEXT", height=5, rotation=30).set_placement((10, 80), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    blk = d.blocks.new("門", base_point=(0, 0))
    blk.add_line((0, 0), (9, 0))
    blk.add_arc((0, 0), 9, 0, 90)
    m.add_blockref("門", (200, 0), dxfattribs={"xscale": 2, "yscale": 2, "rotation": 90})
    if version != "R12":
        m.add_lwpolyline([(0, 0, 0), (10, 0, 1), (10, 10, 0)], format="xyb", close=True)
        m.add_ellipse((100, 100), major_axis=(30, 0), ratio=0.5, start_param=0, end_param=math.pi)
        m.add_spline(fit_points=[(0, 200), (10, 210), (20, 200)])
        s = m.add_spline(degree=3)
        s.control_points = [(0, 300, 0), (10, 320, 0), (30, 320, 0), (40, 300, 0)]
        s.knots = [0, 0, 0, 0, 1, 1, 1, 1]
        m.add_mtext("第一行\\P{\\fArial|b1;粗體}第二行", dxfattribs={"char_height": 4, "insert": (0, 400)})
        h = m.add_hatch(color=2)
        h.paths.add_polyline_path([(300, 0), (340, 0), (340, 30), (300, 30)], is_closed=True)
        h2 = m.add_hatch()
        h2.set_pattern_fill("ANSI31", scale=2)
        ep = h2.paths.add_edge_path()
        ep.add_line((400, 0), (440, 0))
        ep.add_arc((440, 10), 10, 270, 90, ccw=True)
        ep.add_line((440, 20), (400, 20))
        ep.add_line((400, 20), (400, 0))
        m.add_linear_dim(base=(50, -20), p1=(0, 0), p2=(100, 0)).render()
        m.add_xline((0, 0), (1, 1, 0))
    else:
        m.add_polyline2d([(0, 0, 0, 0, 0), (10, 0, 0, 0, 1), (10, 10, 0, 0, 0)], format="xyseb", close=True)
        m.add_solid([(300, 0), (340, 0), (300, 30), (340, 30)])
    path = os.path.join(TMP, "ref_%s.dxf" % version)
    d.saveas(path)
    return path


@pytest.mark.parametrize("version", ["R2010", "R2018", "R12"])
def test_import(version):
    doc = IO.import_dxf(make_reference(version))
    by = lambda cls: [e for e in doc.entities if isinstance(e, cls)]
    ok("牆" in doc.layers and doc.layers["牆"].color == 1 and doc.layers["牆"].ltype.upper() == "CENTER", "layer table")
    ok(not doc.layers["HIDDEN_OFF"].on, "layer off flag")
    ln = by(Line)[0]
    ok(ln.layer == "牆" and near(ln.x2, 100), "line + unicode layer")
    ok(near(by(Circle)[0].r, 20) and by(Circle)[0].color == 5, "circle color")
    a = by(Arc)[0]
    ok(near(a.a0, 30) and near(a.a1, 120), "arc angles")
    t = by(Text)[0]
    ok(t.text == "單行 TEXT" and t.halign == 1 and t.valign == 2 and near(t.rot, 30) and near(t.x, 10), "text align")
    ins = [e for e in by(Insert) if e.name == "門"][0]
    ok(near(ins.sx, 2) and near(ins.rot, 90) and len(doc.blocks["門"].entities) == 2, "insert + block")
    bb = doc.bbox(ins)
    ok(near(bb[0], 182) and near(bb[3], 18), "insert expansion bbox")
    pl = by(Polyline)[0]
    ok(pl.closed and near(pl.pts[1][2], 1.0) and len(pl.pts) == 3, "polyline bulge")
    hs = by(Hatch)
    ok(len(hs) >= 1 and near(hs[0].area(), 1200), "solid fill")
    if version != "R12":
        el = by(Ellipse)[0]
        ok(near(el.ratio, 0.5) and not el.full(), "ellipse arc")
        sp = by(Spline)
        ok(len(sp) == 2 and len(sp[1].points()) > 10, "splines")
        ok(near(sp[1].points()[0][1], 300) and near(sp[1].points()[-1][0], 40, 1e-3), "bspline evaluation")
        mt = by(MText)[0]
        ok(mt.text == "第一行\n粗體第二行", "mtext formatting stripped")
        ok(hs[1].pattern == "ANSI31" and near(hs[1].area(), 800 + math.pi * 50, 1.0), "hatch edge path with arc")
        dims = by(Dim)
        ok(len(dims) == 1 and dims[0].kind == "LIN" and near(dims[0].measure(),100), "editable dimension import")
        ok(len(by(XLine)) == 1, "xline")
    ok(not doc.report["skipped"], "nothing skipped: %s" % doc.report["skipped"])



def sample_doc():
    d = Document()
    d.layers["標註"] = Layer("標註", color=3)
    d.layers["中心線"] = Layer("中心線", color=1, ltype="CENTER")
    d.blocks["B1"] = Block("B1", 0, 0, [Line(x1=0, y1=0, x2=5, y2=0), Circle(cx=0, cy=0, r=2, color=0)])
    d.entities = [
        Line(x1=0, y1=0, x2=100, y2=0, layer="中心線"), Circle(cx=50, cy=30, r=20, color=3),
        Arc(cx=50, cy=30, r=28, a0=350, a1=90), Polyline(pts=[(0, 0, 0), (10, 0, 1), (10, 10, 0)], closed=True),
        Ellipse(cx=180, cy=20, mx=20, my=5, ratio=0.4), Spline(fit=[(110, 60), (130, 80), (150, 60)]),
        Point(x=1, y=2), Text(x=0, y=70, text="中文 Text", height=5, rot=15, halign=1, valign=2),
        MText(x=60, y=95, text="多行\n第二行", height=4), Hatch(loops=[[(200, 0), (240, 0), (240, 30), (200, 30)]],
                                                            pattern="ANSI31", scale=2),
        Hatch(loops=[[(0, 0), (1, 0), (0, 1)]], pattern="SOLID"),
        Dim(kind="LIN", pts=[(0, 0), (100, 0), (50, -15)], layer="標註"), Dim(kind="ALI", pts=[(0, 0), (30, 40), (0, 40)]),
        Dim(kind="RAD", pts=[(50, 30), (70, 30), (80, 30)]), Dim(kind="DIA", pts=[(50, 30), (70, 30), (60, 30)]),
        Dim(kind="ANG", pts=[(0, 0), (10, 0), (0, 10), (5, 5)]), Dim(kind="LDR", pts=[(0, 0), (10, 10)], text="註"),
        XLine(x=0, y=0, dx=1, dy=1), Insert(name="B1", x=10, y=10, sx=2, sy=2, rot=45, color=2),
    ]
    return d


def test_export_2010():
    d = sample_doc()
    p = os.path.join(TMP, "out2010.dxf")
    IO.export_dxf_2010(p, d)
    r = ezdxf.readfile(p)
    aud = r.audit()
    ok(not aud.errors, "ezdxf audit clean: %s" % [e.message for e in aud.errors])
    types = [e.dxftype() for e in r.modelspace()]
    for t in ("LINE", "CIRCLE", "ARC", "LWPOLYLINE", "ELLIPSE", "SPLINE", "POINT", "TEXT", "MTEXT", "HATCH",
              "DIMENSION", "XLINE", "INSERT"):
        ok(t in types, "2010 export has " + t)
    ok(types.count("DIMENSION") == 5, "real DIMENSION entities")
    ok(r.layers.get("中心線").dxf.linetype == "CENTER", "layer linetype")
    # 自己再讀回來
    back = IO.import_dxf(p)
    ok(len([e for e in back.entities if isinstance(e, Ellipse)]) == 1, "roundtrip ellipse")
    ok([e for e in back.entities if isinstance(e, Text)][0].text == "中文 Text", "roundtrip unicode text")
    ok(near([e for e in back.entities if isinstance(e, Arc)][0].a0, 350), "roundtrip arc")
    ok("B1" in back.blocks, "roundtrip block")


def test_export_r12():
    d = sample_doc()
    p = os.path.join(TMP, "out12.dxf")
    IO.export_dxf_r12(p, d)
    r = ezdxf.readfile(p)
    ok(r.dxfversion == "AC1009", "R12 version")
    types = [e.dxftype() for e in r.modelspace()]
    ok("POLYLINE" in types and "INSERT" in types and "SOLID" in types, "R12 entity set")
    ok("ELLIPSE" not in types and "LWPOLYLINE" not in types, "R12 has no R13+ entities")
    back = IO.import_dxf(p)
    ok("中心線" in back.layers and back.layers["中心線"].color == 1, "R12 unicode layer roundtrip")
    ok(any(isinstance(e, Text) and e.text == "中文 Text" for e in back.entities), "R12 unicode text roundtrip")
    pl = [e for e in back.entities if isinstance(e, Polyline) and e.closed and len(e.pts) == 3][0]
    ok(near(pl.pts[1][2], 1.0), "R12 bulge roundtrip")


def test_pycad_and_legacy():
    d = sample_doc()
    p = os.path.join(TMP, "a.pycad")
    IO.save_project(p, d)
    b = IO.load_project(p)
    ok(len(b.entities) == len(d.entities) and b.layers["中心線"].ltype == "CENTER", "pycad roundtrip")
    ok(b.entities[11].label() == "100", "dimension survives")
    import json
    old = {"format": "PyCAD2D", "version": 4, "entities": [
        {"type": "LineEntity", "layer": "0", "x1": 0, "y1": 0, "x2": 5, "y2": 5},
        {"type": "RectEntity", "layer": "0", "x1": 0, "y1": 0, "x2": 5, "y2": 5},
        {"type": "ArcEntity", "layer": "0", "cx": 0, "cy": 0, "radius": 3, "start_angle": 90, "span_angle": -90},
        {"type": "PolylineEntity", "layer": "0", "points": [[0, 0], [1, 1], [2, 0]]},
        {"type": "TextEntity", "layer": "0", "x": 0, "y": 0, "text": "hi", "height": 12},
        {"type": "LinearDimEntity", "layer": "0", "x1": 0, "y1": 0, "x2": 10, "y2": 0, "lx": 5, "ly": 5}]}
    p4 = os.path.join(TMP, "old.pycad")
    json.dump(old, open(p4, "w"))
    b = IO.load_project(p4)
    ok(len(b.entities) == 6 and isinstance(b.entities[1], Polyline) and b.entities[1].closed, "v0.4 file loads")
    ok(near(b.entities[2].a0, 0) and near(b.entities[2].a1, 90), "v0.4 clockwise arc converted")


def test_render_outputs():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from pycad2d import render as R
    d = sample_doc()
    for fn, name in ((R.export_pdf, "o.pdf"), (R.export_svg, "o.svg"), (R.export_png, "o.png")):
        p = os.path.join(TMP, name)
        fn(d, p)
        ok(os.path.getsize(p) > 1000, "export " + name)


if __name__ == "__main__":
    test_import("R2010")
    print("ok   import R2010")
    test_import("R2018")
    print("ok   import R2018")
    test_import("R12")
    print("ok   import R12")
    test_export_2010()
    print("ok   export 2010")
    test_export_r12()
    print("ok   export R12")
    test_pycad_and_legacy()
    print("ok   pycad + legacy")
    test_render_outputs()
    print("ok   pdf/svg/png")
    print("全部通過：%d 項檢查" % N)
