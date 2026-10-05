# SPDX-License-Identifier: GPL-3.0-only
"""主視窗整合測試（無頭模式）。  執行： python tests/test_ui.py"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pycad2d.app import MainWindow
from pycad2d import commands as C
from pycad2d import io_utils as IO
from pycad2d.model import *
from pycad2d.panels import DraftingSettings, PlotDialog, ColorDialog

TMP = tempfile.mkdtemp(prefix="pycad_ui_")
N = 0


def ok(cond, name):
    global N
    if not cond:
        raise AssertionError("FAIL: " + name)
    N += 1


def make():
    w = MainWindow()
    w.resize(1400, 850)
    w.show()
    app.processEvents()
    w.ask_text = lambda *a, **k: "測試文字"
    w.ask_choice = lambda t, l, items, cur=None: items[0]
    w.settings.osnap = False
    w.settings.polar = False
    return w


def log(w):
    return w.cmdline.log.toPlainText()


def click(w, pt, shift=False):
    cv = w.canvas
    p = cv.view.w2s(*pt)
    cv.move_to(p)
    cv.click(p, shift)
    cv.release(p, shift)


def feed(w, *items):
    for x in items:
        if isinstance(x, tuple):
            click(w, x)
        else:
            w.on_submit(x)


def test_command_line():
    w = make()
    cv = w.canvas
    feed(w, "L", "0,0", "100,0", "100,50", "C")
    ok(len(cv.doc.entities) == 3 and not cv.busy(), "typed LINE")
    feed(w, "", "0,100", "50,100", "")
    ok(len(cv.doc.entities) == 4, "empty Enter repeats LINE")
    feed(w, "NOSUCHCMD")
    ok("未知的指令" in log(w), "unknown command message")
    feed(w, "_line", "0,200", "@10<90", "")
    ok(abs(cv.doc.entities[-1].y2 - 210) < 1e-9, "underscore prefix + polar input")
    feed(w, "DT", "0,300", "5", "0", "hello big world", "")
    ok(cv.doc.entities[-1].text == "hello big world", "text with spaces")
    feed(w, "LTSCALE", "2.5")
    ok(cv.doc.vars["LTSCALE"] == 2.5, "system variable")
    feed(w, "U")
    ok(cv.doc.vars["LTSCALE"] == 1.0, "undo restores variable")
    # 真的敲鍵盤：在畫布上打字會進到指令行，空白鍵等於 Enter
    cv.setFocus()
    QTest.keyClicks(cv, "c")
    ok(w.cmdline.edit.text() == "c", "typing on canvas goes to command line")
    QTest.keyClick(w.cmdline.edit, Qt.Key.Key_Space)
    ok(cv.busy() and cv.cmd_name == "CIRCLE", "space starts command")
    ok("指定圓的中心點" in w.cmdline.prompt.text(), "prompt shown")
    QTest.keyClick(w.cmdline.edit, Qt.Key.Key_Escape)
    ok(not cv.busy(), "escape cancels")
    # 提示中的關鍵字可以用點的
    feed(w, "C", "0,0")
    w.cmdline.keyword.emit("D")
    ok("直徑" in cv.req.prompt, "clickable keyword")
    feed(w, "40")
    ok(cv.doc.entities[-1].r == 20, "diameter via keyword")
    w.close_tab = lambda i: True
    return w


def test_every_command_smoke():
    """每個指令都跑一遍：亂點幾下、按幾次 Enter，不能丟例外。"""
    w = make()
    cv = w.canvas
    feed(w, "REC", "0,0", "100,60")
    feed(w, "C", "50,30", "15")
    feed(w, "L", "-20,30", "120,30", "")
    feed(w, "L", "150,0", "150,60", "")
    feed(w, "L", "150,0", "220,0", "")
    feed(w, "DT", "0,80", "5", "0", "abc", "")
    feed(w, "B", "BLK", "150,0", (150, 30), "")
    pts = [(50, 45), (100, 30), (150, 30), (30, 0), (200, 0), (60, 90), (10, 10)]
    for name in sorted(C.COMMANDS):
        for variant in range(3):
            w.run_command(name)
            for k in range(7):
                if not cv.busy():
                    break
                if variant == 0:
                    click(w, pts[k % len(pts)])
                elif variant == 1:
                    (click(w, pts[k]) if k % 2 == 0 else cv.enter())
                else:
                    if cv.req.keywords and k < len(cv.req.keywords):
                        w.on_submit(cv.req.keywords[k][0])
                    elif cv.req.kind in ("num", "text"):
                        w.on_submit("3")
                    else:
                        click(w, pts[(k + 2) % len(pts)])
            for _ in range(4):
                if cv.busy():
                    cv.enter()
            cv.cancel(silent=True)
            ok("指令發生錯誤" not in log(w), "command %s (variant %d) raised: %s" % (name, variant, log(w)[-300:]))
            cv.update()
            app.processEvents()
    for name in list(w.ui_commands):
        if name in ("NEW", "OPEN", "SAVE", "SAVEAS", "CLOSE", "QUIT", "PLOT", "HELP", "COLOR", "DSETTINGS", "DDEDIT") \
                or name.startswith("EXPORT"):
            continue
        w.run_command(name)
        cv.cancel(silent=True)
    ok("指令發生錯誤" not in log(w), "ui commands")
    cv.doc.modified = False


def test_palettes():
    w = make()
    cv = w.canvas
    d = cv.doc
    feed(w, "C", "0,0", "10")
    feed(w, "L", "0,0", "50,0", "")
    w.toggle_properties()
    app.processEvents()
    ok(w.props_dock.isVisible() and w.props.table.rowCount() > 5, "properties palette (no selection)")
    click(w, (10, 0.0001))
    c = [e for e in cv.selection if isinstance(e, Circle)]
    cv.set_selection([e for e in d.entities if isinstance(e, Circle)])
    app.processEvents()
    rows = {w.props.table.item(r, 0).text(): r for r in range(w.props.table.rowCount()) if w.props.table.item(r, 0)}
    ok("半徑" in rows and w.props.head.text() == "圓 (1)", "geometry rows")
    w.props.table.item(rows["半徑"], 1).setText("25")
    ok(cv.selection[0].r == 25 and d.entities[0].r == 25, "edit radius in palette")
    feed(w, "U")
    ok(d.entities[0].r == 10, "palette edit is undoable")
    # 每一種圖元都能顯示
    cv.cancel()
    feed(w, "REC", "100,0", "140,30")
    feed(w, "EL", "0,100", "40,100", "5")
    feed(w, "DLI", "0,0", "50,0", "25,-20")
    feed(w, "H", "S", (100, 15), "", "")
    feed(w, "MT", "200,50", "260,20")
    feed(w, "SPL", "0,200", "10,210", "20,200", "")
    feed(w, "PO", "5,5", "")
    feed(w, "XL", "0,300", "10,310", "")
    for e in list(d.entities):
        cv.set_selection([e])
        app.processEvents()
        ok(w.props.table.rowCount() >= 6, "palette for " + e.NAME)
    cv.set_selection(list(d.entities))
    ok(w.props.head.text().startswith("全部"), "mixed selection")
    # 功能區圖層清單：有選取就搬圖層，沒選取就改目前圖層
    w.show_layers()
    app.processEvents()
    lm = w.layers
    lm.new_layer()
    lm.table.closePersistentEditor(lm.table.currentItem())
    ok("圖層1" in d.layers, "new layer")
    row = list(d.layers).index("圖層1")
    lm.table.item(row, 1).setText("牆")
    ok("牆" in d.layers and "圖層1" not in d.layers, "rename layer")
    row = list(d.layers).index("牆")
    lm.on_click(row, 2)
    ok(not d.layers["牆"].on, "toggle layer on/off")
    lm.on_click(row, 2)
    lm.table.setCurrentCell(row, 1)
    lm.set_current()
    ok(d.current_layer == "牆", "set current layer")
    cv.set_selection([d.entities[0]])
    w.on_layer_combo(w.layer_combo.keys.index("0"))
    ok(d.current_layer == "牆" and cv.selection[0].layer == "0", "layer combo moves selection")
    cv.set_selection([])
    w.on_layer_combo(w.layer_combo.keys.index("0"))
    ok(d.current_layer == "0", "layer combo sets current")
    lm.table.setCurrentCell(list(d.layers).index("牆"), 1)
    lm.delete_layer()
    ok("牆" not in d.layers, "delete unused layer")
    # 顏色／線型
    cv.set_selection([d.entities[1]])
    w.apply_prop("color", "CECOLOR", 1)
    w.apply_prop("ltype", "CELTYPE", "DASHED")
    ok(cv.selection[0].color == 1 and cv.selection[0].ltype == "DASHED", "ribbon color/linetype")
    cv.set_selection([])
    w.apply_prop("color", "CECOLOR", 3)
    feed(w, "L", "0,400", "10,400", "")
    ok(d.entities[-1].color == 3, "current color applies to new objects")
    # 對話框
    s = w.settings
    dlg = DraftingSettings(w, s)
    dlg.modes["TAN"].setChecked(True)
    dlg.inc.setCurrentIndex(2)
    dlg.c_polar.setChecked(True)
    dlg.apply()
    ok("TAN" in s.modes and s.polar_inc == 45.0, "drafting settings")
    w.toggle("ortho", True)
    ok(s.ortho and not s.polar, "ortho turns polar off")
    w.toggle("polar", True)
    ok(s.polar and not s.ortho, "polar turns ortho off")
    ok(PlotDialog(w).options()["paper"] == "A3", "plot dialog")
    ColorDialog(w, 5)
    lm.close()
    d.modified = False


def test_files_and_tabs():
    w = make()
    cv = w.canvas
    feed(w, "REC", "0,0", "100,60")
    feed(w, "C", "50,30", "15")
    feed(w, "DT", "0,80", "5", "0", "中文", "")
    ok("*" in w.windowTitle(), "modified flag in title")
    p = os.path.join(TMP, "a.pycad")
    cv.doc.path = p
    ok(w.save_file() and os.path.exists(p) and "*" not in w.windowTitle(), "save")
    # 複製、開新圖、貼上
    cv.select_all()
    w.run_command("COPYCLIP")
    w.new_file()
    ok(w.tabs.count() == 2 and w.canvas is not cv and len(w.canvas.doc.entities) == 0, "new tab")
    w.run_command("PASTECLIP")
    feed(w, "10,10")
    ok(len(w.canvas.doc.entities) == 3, "paste into another drawing")
    w.canvas.doc.modified = False
    # 匯出 DXF 再開回來
    dxf = os.path.join(TMP, "a.dxf")
    IO.export_dxf(dxf, cv.doc)
    c2 = w.open_file(dxf)
    ok(c2 is not None and len(c2.doc.entities) == 3 and c2.doc.source == "DXF" and c2.doc.path is None, "open DXF")
    ok("已匯入" in log(w), "import report")
    c3 = w.open_file(p)
    ok(c3.doc.path == p and len(c3.doc.entities) == 3, "open pycad")
    n = w.tabs.count()
    w.tabs.setCurrentIndex(0)
    ok(w.canvas is cv and "a.pycad" in w.windowTitle(), "switch tab")
    ok(w.close_tab(n - 1) and w.tabs.count() == n - 1, "close tab")
    # 輸出
    from pycad2d import render as R
    R.export_pdf(cv.doc, os.path.join(TMP, "a.pdf"), paper="A4", units_per_mm=1.0)
    ok(os.path.getsize(os.path.join(TMP, "a.pdf")) > 1000, "plot pdf 1:1")
    for c in w.canvases():
        c.doc.modified = False


if __name__ == "__main__":
    for t in (test_command_line, test_every_command_smoke, test_palettes, test_files_and_tabs):
        t()
        print("ok  ", t.__name__)
    print("全部通過：%d 項檢查" % N)
