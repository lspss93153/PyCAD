# SPDX-License-Identifier: GPL-3.0-only
"""無頭測試：用指令行文字與模擬點擊驅動整個指令流程。  執行： python tests/test_core.py"""
import os
import sys
import math

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pycad2d.canvas import CadCanvas
from pycad2d.model import *
from pycad2d import geometry as G

PASSED = 0


def ok(cond, name):
    global PASSED
    if not cond:
        raise AssertionError("FAIL: " + name)
    PASSED += 1


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def new_canvas():
    c = CadCanvas()
    c.resize(1000, 700)
    c.show()
    c.s.osnap = False
    c.s.polar = False
    c.log = []
    c.history.connect(c.log.append)
    return c


def run(c, *inputs):
    """第一個字串是指令名稱，其餘是輸入；tuple 表示在該世界座標點一下。"""
    from pycad2d.commands import ALIASES
    name = inputs[0].upper()
    ok(c.start_command(ALIASES.get(name, name)), "start " + name)
    for x in inputs[1:]:
        if isinstance(x, tuple):
            click(c, x)
        else:
            ok(c.feed_text(x), "feed %r" % x)


def click(c, w, shift=False):
    p = c.view.w2s(*w)
    c.move_to(p)
    c.click(p, shift)


def test_draw():
    c = new_canvas()
    run(c, "L", "0,0", "100,0", "@0,50", "@50<180", "C")
    ok(len(c.doc.entities) == 4 and not c.busy(), "line closes")
    ok(near(c.doc.entities[2].x2, 50) and near(c.doc.entities[2].y2, 50), "relative polar")
    run(c, "C", "50,25", "10")
    ok(isinstance(c.doc.entities[-1], Circle) and near(c.doc.entities[-1].r, 10), "circle radius")
    run(c, "C", "50,25", "D", "30")
    ok(near(c.doc.entities[-1].r, 15), "circle diameter")
    run(c, "C", "3P", "0,0", "10,0", "0,10")
    ok(near(c.doc.entities[-1].cx, 5) and near(c.doc.entities[-1].cy, 5), "circle 3P")
    run(c, "REC", "200,0", "@40,20")
    e = c.doc.entities[-1]
    ok(isinstance(e, Polyline) and e.closed and near(e.area(), 800), "rectangle")
    run(c, "A", "0,0", "5,5", "10,0")
    e = c.doc.entities[-1]
    ok(isinstance(e, Arc) and near(e.r, 5) and near(e.cx, 5), "arc 3 points")
    run(c, "POL", "6", "300,100", "I", "20")
    ok(len(c.doc.entities[-1].pts) == 6, "polygon")
    run(c, "EL", "0,100", "40,100", "5")
    e = c.doc.entities[-1]
    ok(isinstance(e, Ellipse) and near(e.ratio, 0.25), "ellipse")
    run(c, "PL", "0,200", "10,200", "A", "10,210", "L", "0,210", "C")
    e = c.doc.entities[-1]
    ok(e.closed and len(e.pts) == 4 and near(e.pts[1][2], 1.0), "pline with arc")
    run(c, "SPL", "0,300", "10,310", "20,300", "30,310", "")
    ok(isinstance(c.doc.entities[-1], Spline), "spline")
    run(c, "XL", "H", "0,400", "")
    ok(isinstance(c.doc.entities[-1], XLine), "xline")
    run(c, "DT", "0,500", "5", "0", "Hello 測試", "")
    ok(c.doc.entities[-1].text == "Hello 測試" and not c.busy(), "text keeps spaces")
    n = len(c.doc.entities)
    c.undo()
    ok(len(c.doc.entities) == n - 1, "undo")
    c.redo()
    ok(len(c.doc.entities) == n, "redo")
    # 直接距離輸入 + 正交
    c.s.ortho = True
    c.start_command("LINE")
    c.feed_text("0,600")
    c.move_to(c.view.w2s(30, 603))
    c.feed_text("25")
    c.feed_text("")
    e = c.doc.entities[-1]
    ok(near(e.x2, 25) and near(e.y2, 600), "direct distance with ortho")
    c.s.ortho = False


def test_modify():
    c = new_canvas()
    run(c, "L", "0,0", "100,0", "")
    run(c, "M", "ALL", "", "0,0", "10,10")
    e = c.doc.entities[0]
    ok(near(e.x1, 10) and near(e.y2, 10), "move")
    run(c, "CO", "ALL", "", "0,0", "0,20", "0,40", "")
    ok(len(c.doc.entities) == 3, "copy multiple")
    run(c, "RO", "L", "", "10,50", "90")
    e = c.doc.entities[-1]
    ok(near(e.x2, 10) and near(e.y2, 150), "rotate")
    run(c, "SC", "L", "", "10,50", "0.5")
    ok(near(c.doc.entities[-1].y2, 100), "scale")
    run(c, "MI", "L", "", "0,0", "0,10", "N")
    ok(len(c.doc.entities) == 4 and near(c.doc.entities[-1].x1, -10), "mirror keeps source")
    run(c, "E", "ALL", "")
    ok(len(c.doc.entities) == 0, "erase all")
    # offset
    run(c, "REC", "0,0", "100,50")
    run(c, "O", "5", (0, 25), (50, 25), "")
    ok(len(c.doc.entities) == 2 and near(c.doc.entities[-1].area(), 90 * 40), "offset inside")
    # trim / extend
    run(c, "E", "ALL", "")
    run(c, "L", "0,0", "100,0", "")
    run(c, "L", "30,-20", "30,20", "")
    run(c, "L", "70,-20", "70,20", "")
    run(c, "TR", "", (50, 0), "")
    ok(len(c.doc.entities) == 4, "trim middle splits line")
    run(c, "L", "0,10", "20,10", "")
    run(c, "EX", "", (19, 10), "")
    ok(near(c.doc.entities[-1].x2, 30), "extend to boundary")
    # fillet
    run(c, "E", "ALL", "")
    run(c, "L", "0,0", "50,0", "")
    run(c, "L", "0,0", "0,50", "")
    run(c, "F", "R", "10", (40, 0), (0, 40))
    arcs = [e for e in c.doc.entities if isinstance(e, Arc)]
    ok(len(arcs) == 1 and near(arcs[0].r, 10) and near(arcs[0].cx, 10), "fillet")
    run(c, "E", "ALL", "")
    run(c, "L", "0,0", "50,0", "")
    run(c, "L", "0,0", "0,50", "")
    run(c, "CHA", "D", "5", "8", (40, 0), (0, 40))
    ok(len(c.doc.entities) == 3, "chamfer")
    # array / explode / join
    run(c, "E", "ALL", "")
    run(c, "C", "0,0", "5")
    run(c, "AR", "ALL", "", "R", "2", "3", "20", "20")
    ok(len(c.doc.entities) == 1 and isinstance(c.doc.entities[0], Array) and c.doc.entities[0].rows == 2 and c.doc.entities[0].cols == 3, "rect associative array")
    run(c, "E", "ALL", "")
    run(c, "C", "50,0", "5")
    run(c, "AR", "ALL", "", "PO", "0,0", "8", "360", "Y")
    ok(len(c.doc.entities) == 1 and isinstance(c.doc.entities[0], Array) and c.doc.entities[0].count == 8, "polar associative array")
    run(c, "E", "ALL", "")
    run(c, "REC", "0,0", "10,10")
    run(c, "X", "ALL", "")
    ok(len(c.doc.entities) == 4 and all(isinstance(e, Line) for e in c.doc.entities), "explode")
    run(c, "J", "ALL", "")
    ok(len(c.doc.entities) == 1 and c.doc.entities[0].closed, "join")
    run(c, "F", "R", "2", "P", (5, 0))
    ok(len(c.doc.entities[0].pts) == 8, "fillet polyline")
    # stretch（由右往左框選）
    run(c, "E", "ALL", "")
    run(c, "REC", "0,0", "100,50")
    c.start_command("STRETCH")
    a, b = c.view.w2s(120, 60), c.view.w2s(80, -10)
    c.move_to(a); c.click(a); c.release(a); c.move_to(b); c.click(b)
    c.feed_text("")
    c.feed_text("0,0"); c.feed_text("20,0")
    e = c.doc.entities[0]
    ok(near(max(p[0] for p in e.pts), 120) and near(min(p[0] for p in e.pts), 0), "stretch")
    # break
    run(c, "E", "ALL", "")
    run(c, "L", "0,0", "100,0", "")
    run(c, "BR", (30, 0), "60,0")
    ok(len(c.doc.entities) == 2, "break")
    # grips
    run(c, "E", "ALL", "")
    run(c, "L", "0,0", "100,0", "")
    click(c, (50, 0))
    ok(len(c.selection) == 1, "pick selects")
    click(c, (100, 0))
    ok(c.busy(), "grip starts stretch")
    click(c, (100, 40))
    ok(near(c.doc.entities[0].y2, 40) and len(c.selection) == 1, "grip stretch")
    # 先選取再下指令
    c.cancel()
    click(c, (0, 0))
    c.start_command("ERASE")
    ok(len(c.doc.entities) == 0 and not c.busy(), "noun-verb erase")


def test_annotation():
    c = new_canvas()
    run(c, "L", "0,0", "100,0", "")
    run(c, "DLI", "0,0", "100,0", "50,20")
    d = c.doc.entities[-1]
    ok(isinstance(d, Dim) and d.label() == "100", "linear dim")
    run(c, "DAL", "0,0", "30,40", "0,40")
    ok(c.doc.entities[-1].label() == "50", "aligned dim")
    run(c, "C", "200,0", "25")
    run(c, "DRA", (225, 0), "240,20")
    ok(c.doc.entities[-1].label() == "R25", "radius dim")
    run(c, "DDI", (225, 0), "240,20")
    ok(c.doc.entities[-1].label() == "Ø50", "diameter dim")
    run(c, "L", "0,100", "50,100", "")
    run(c, "L", "0,100", "0,150", "")
    run(c, "DAN", (40, 100), (0, 140), "20,120")
    ok(c.doc.entities[-1].label() == "90°", "angular dim")
    # 拉伸標註後數值自動更新
    d2 = d.grip_moved(1, (150, 0))
    ok(d2.label() == "150", "dimension updates")
    # hatch
    run(c, "REC", "300,0", "340,30")
    run(c, "H", "320,15", "")
    h = c.doc.entities[-1]
    ok(isinstance(h, Hatch) and near(h.area(), 1200), "hatch pick point")
    run(c, "DI", "0,0", "30,40")
    ok(any("距離 = 50" in s for s in c.log), "dist")
    run(c, "AA", "O", (300, 15))
    ok(any("面積 = 1200" in s for s in c.log), "area")


def test_layers_blocks():
    c = new_canvas()
    d = c.doc
    d.layers["牆"] = Layer("牆", color=1, ltype="CENTER")
    d.current_layer = "牆"
    run(c, "L", "0,0", "10,0", "")
    e = d.entities[-1]
    ok(e.layer == "牆" and d.color_of(e) == 1 and d.ltype_of(e) == "CENTER", "bylayer props")
    run(c, "C", "5,5", "2")
    run(c, "B", "門", "0,0", "ALL", "")
    ok(len(d.entities) == 1 and isinstance(d.entities[0], Insert) and "門" in d.blocks, "block")
    d.vars["INSNAME"] = "門"
    c.ui = None
    run(c, "I", "門", "100,100")
    ok(len(d.entities) == 2 and near(d.bbox(d.entities[-1])[0], 100), "insert")
    run(c, "X", "L", "")
    ok(len(d.entities) == 3, "explode insert")
    d.layers["牆"].locked = True
    c.invalidate()
    ok(c.pick((105, 105)) is None, "locked layer not pickable")
    d.layers["牆"].locked = False
    run(c, "LAYFRZ", (105, 107), "")
    ok(not d.layers["牆"].frozen, "cannot freeze current layer")
    # 存檔/讀檔
    import json
    d2 = Document.from_json(json.loads(json.dumps(d.to_json())))
    ok(len(d2.entities) == 3 and "門" in d2.blocks and d2.layers["牆"].ltype == "CENTER", "json roundtrip")


def test_osnap():
    c = new_canvas()
    run(c, "L", "0,0", "100,0", "")
    run(c, "L", "50,-50", "50,50", "")
    run(c, "C", "200,0", "20")
    run(c, "L", "0,80", "40,80", "")
    c.s.osnap = True
    c.s.modes = {"END", "MID", "CEN", "INT", "QUA", "PER", "TAN"}
    c.start_command("LINE")
    off = 4 / c.view.scale
    for target, kind in (((100, 0), "END"), ((50, 0), "INT"), ((20, 80), "MID"), ((220, 0), "QUA")):
        c.move_to(c.view.w2s(target[0] + off, target[1] + off))
        ok(c.snap_hit is not None and c.snap_hit[0] == kind and near(c.snap_hit[1][0], target[0]), "osnap " + kind)
    c.move_to(c.view.w2s(200 + 20 * math.cos(1.0) + off, 20 * math.sin(1.0)))
    ok(c.snap_hit is not None and c.snap_hit[0] == "CEN", "osnap CEN by hovering circle")
    c.feed_text("0,30")
    c.move_to(c.view.w2s(40, off))
    ok(c.snap_hit is not None and c.snap_hit[0] == "PER" and near(c.snap_hit[1][0], 0), "osnap PER")
    c.cancel()
    c.s.osnap = False
    c.s.polar = True
    c.s.polar_inc = 45
    c.start_command("LINE")
    c.feed_text("0,0")
    c.move_to(c.view.w2s(50, 51))
    ok(c.track is not None and near(c.track[1], 45) and near(c.cur_pt[0], c.cur_pt[1]), "polar tracking")
    c.cancel()


if __name__ == "__main__":
    for t in (test_draw, test_modify, test_annotation, test_layers_blocks, test_osnap):
        t()
        print("ok  ", t.__name__)
    print("全部通過：%d 項檢查" % PASSED)
