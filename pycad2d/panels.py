# SPDX-License-Identifier: GPL-3.0-only
"""選項板與對話框：圖層性質管理員、性質選項板、製圖設定、顏色選取、文字編輯、出圖。"""
import math
from PySide6.QtCore import Qt, Signal, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem,
                               QPushButton, QLabel, QComboBox, QCheckBox, QDoubleSpinBox, QPlainTextEdit,
                               QDialogButtonBox, QWidget, QHeaderView, QAbstractItemView, QMessageBox, QGroupBox,
                               QInputDialog, QToolButton, QLineEdit, QSpinBox, QTabWidget)
from . import geometry as G
from .icons import icon, swatch
from .model import (Layer, Line, Circle, Arc, Polyline, Ellipse, Spline, Point, Text, MText, Hatch, XLine, Dim, Insert, Array, Solid3D,
                    aci_rgb, color_name, lw_name, fmt, BYLAYER, BYBLOCK, LW_BYLAYER, LW_DEFAULT, LINEWEIGHTS,
                    TWO_PI, UNIT_NAMES)
from .render import HATCH_PATTERNS

MULTI = "*多種*"


# ================================================================ 顏色
class _AciGrid(QWidget):
    picked = Signal(int)

    def __init__(self):
        super().__init__()
        self.cell = 17
        self.setFixedSize(24 * self.cell + 2, 10 * self.cell + 2 + 30 + self.cell * 2 + 16)
        self.setMouseTracking(True)
        self.hover = None

    def _cells(self):
        c = self.cell
        for col in range(24):
            for row in range(10):
                # 上半：偶數色號由暗到亮；下半：奇數色號
                idx = 10 + col * 10 + (8 - 2 * row if row < 5 else 1 + 2 * (row - 5))
                yield idx, QRectF(1 + col * c, 1 + row * c, c - 1, c - 1)
        y = 10 * c + 14
        for i in range(1, 10):
            yield i, QRectF(1 + (i - 1) * (c + 6), y, c + 4, c + 4)
        for k, i in enumerate(range(250, 256)):
            yield i, QRectF(1 + (11 + k) * (c + 6), y, c + 4, c + 4)

    def paintEvent(self, ev):
        p = QPainter(self)
        for idx, r in self._cells():
            p.setPen(QPen(QColor("#ffffff") if idx == self.hover else QColor(20, 24, 30), 1))
            p.setBrush(QBrush(QColor(*aci_rgb(idx))))
            p.drawRect(r)

    def _at(self, pos):
        for idx, r in self._cells():
            if r.contains(pos):
                return idx
        return None

    def mouseMoveEvent(self, ev):
        self.hover = self._at(ev.position())
        self.setToolTip("" if self.hover is None else "索引顏色 %d  (%d,%d,%d)" % ((self.hover,) + aci_rgb(self.hover)))
        self.update()

    def mousePressEvent(self, ev):
        i = self._at(ev.position())
        if i is not None:
            self.picked.emit(i)


class ColorDialog(QDialog):
    """AutoCAD 索引顏色 (ACI) 選取。"""

    def __init__(self, parent, current=7, allow_by=True):
        super().__init__(parent)
        self.setWindowTitle("選取顏色")
        self.value = current
        v = QVBoxLayout(self)
        v.addWidget(QLabel("索引顏色 (ACI):"))
        g = _AciGrid()
        g.picked.connect(self._set)
        v.addWidget(g)
        row = QHBoxLayout()
        if allow_by:
            for label, val in (("ByLayer", BYLAYER), ("ByBlock", BYBLOCK)):
                b = QPushButton(label)
                b.clicked.connect(lambda _=False, val=val: self._set(val))
                row.addWidget(b)
        row.addStretch()
        row.addWidget(QLabel("顏色:"))
        self.label = QLabel()
        self.sw = QLabel()
        row.addWidget(self.sw)
        row.addWidget(self.label)
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._set(current)

    def _set(self, v):
        self.value = v
        self.label.setText(color_name(v))
        self.sw.setPixmap(swatch(aci_rgb(v) if 0 < v < 256 else (128, 128, 128), 18).pixmap(18, 18))

    @staticmethod
    def get(parent, current=7, allow_by=True):
        d = ColorDialog(parent, current, allow_by)
        return d.value if d.exec() else None


# ================================================================ 圖層性質管理員
class LayerManager(QDialog):
    COLS = ["狀態", "名稱", "打開", "凍結", "鎖護", "出圖", "顏色", "線型", "線粗"]

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("圖層性質管理員")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.resize(760, 380)
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        for text, slot, tip in (("新圖層", self.new_layer, "建立新圖層 (Alt+N)"), ("刪除圖層", self.delete_layer, "刪除選取的圖層"),
                                ("設為目前", self.set_current, "把選取的圖層設為目前圖層")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch()
        self.info = QLabel()
        bar.addWidget(self.info)
        v.addLayout(bar)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(self.on_click)
        self.table.cellDoubleClicked.connect(self.on_double)
        self.table.itemChanged.connect(self.on_item)
        v.addWidget(self.table)
        self._busy = False

    @property
    def cv(self):
        return self.main.canvas

    def refresh(self):
        if not self.isVisible():
            return
        doc = self.cv.doc
        self._busy = True
        row_sel = self.table.currentRow()
        self.table.setRowCount(len(doc.layers))
        for r, ly in enumerate(doc.layers.values()):
            cur = ly.name == doc.current_layer

            def cell(c, text, editable=False, ic=None):
                it = QTableWidgetItem(text)
                it.setFlags((it.flags() | Qt.ItemFlag.ItemIsEditable) if editable else (it.flags() & ~Qt.ItemFlag.ItemIsEditable))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter if c not in (1, 6, 7, 8) else Qt.AlignmentFlag.AlignVCenter)
                if ic is not None:
                    it.setIcon(ic)
                it.setData(Qt.ItemDataRole.UserRole, ly.name)
                self.table.setItem(r, c, it)

            cell(0, "✔" if cur else "")
            cell(1, ly.name, editable=ly.name != "0")
            cell(2, "", ic=icon("LAYON" if ly.on else "LAYOFF"))
            cell(3, "", ic=icon("LAYFRZ" if ly.frozen else "LAYTHW"))
            cell(4, "", ic=icon("LAYLCK" if ly.locked else "LAYULK"))
            cell(5, "", ic=icon("PLOT" if ly.plot else "ERASE"))
            cell(6, color_name(ly.color), ic=swatch(aci_rgb(ly.color)))
            cell(7, ly.ltype)
            cell(8, lw_name(ly.lw))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        if 0 <= row_sel < self.table.rowCount():
            self.table.setCurrentCell(row_sel, 1)
        self.info.setText("目前圖層: %s　　共 %d 個圖層" % (doc.current_layer, len(doc.layers)))
        self._busy = False

    def showEvent(self, ev):
        super().showEvent(ev)
        self.refresh()

    def _name(self, row):
        it = self.table.item(row, 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _apply(self, fn):
        cv = self.cv
        cv.cancel(silent=True)
        cv.doc.push_undo()
        fn(cv.doc)
        cv.changed()

    def on_click(self, row, col):
        name = self._name(row)
        doc = self.cv.doc
        ly = doc.layers.get(name)
        if ly is None:
            return
        if col == 2:
            self._apply(lambda d: setattr(d.layers[name], "on", not ly.on))
        elif col == 3:
            if name == doc.current_layer and not ly.frozen:
                QMessageBox.information(self, "圖層", "無法凍結目前圖層。")
                return
            self._apply(lambda d: setattr(d.layers[name], "frozen", not ly.frozen))
        elif col == 4:
            self._apply(lambda d: setattr(d.layers[name], "locked", not ly.locked))
        elif col == 5:
            self._apply(lambda d: setattr(d.layers[name], "plot", not ly.plot))
        elif col == 6:
            c = ColorDialog.get(self, ly.color, allow_by=False)
            if c:
                self._apply(lambda d: setattr(d.layers[name], "color", c))
        elif col == 7:
            names = sorted(doc.linetypes.keys(), key=lambda s: (s != "Continuous", s))
            s, okk = QInputDialog.getItem(self, "選取線型", "線型:", names, names.index(ly.ltype) if ly.ltype in names else 0, False)
            if okk:
                self._apply(lambda d: setattr(d.layers[name], "ltype", s))
        elif col == 8:
            vals = [LW_DEFAULT] + LINEWEIGHTS
            s, okk = QInputDialog.getItem(self, "線粗", "線粗:", [lw_name(x) for x in vals],
                                          vals.index(ly.lw) if ly.lw in vals else 0, False)
            if okk:
                v = vals[[lw_name(x) for x in vals].index(s)]
                self._apply(lambda d: setattr(d.layers[name], "lw", v))

    def on_double(self, row, col):
        if col == 0:
            self.table.setCurrentCell(row, 1)
            self.set_current()

    def on_item(self, it):
        if self._busy or it.column() != 1:
            return
        old, new = it.data(Qt.ItemDataRole.UserRole), it.text().strip()
        doc = self.cv.doc
        if not new or new == old:
            self.refresh()
            return
        if new in doc.layers:
            QMessageBox.warning(self, "圖層", "圖層「%s」已經存在。" % new)
            self.refresh()
            return

        def rename(d):
            d.layers = {(new if k == old else k): v for k, v in d.layers.items()}
            d.layers[new].name = new
            d.entities = [e.clone(layer=new) if e.layer == old else e for e in d.entities]
            for b in d.blocks.values():
                b.entities = [e.clone(layer=new) if e.layer == old else e for e in b.entities]
            d.block_rev += 1
            if d.current_layer == old:
                d.current_layer = new

        self._apply(rename)

    def new_layer(self):
        doc = self.cv.doc
        i = 1
        while "圖層%d" % i in doc.layers:
            i += 1
        name = "圖層%d" % i
        base = doc.layers.get(self._name(self.table.currentRow()) or doc.current_layer)

        def add(d):
            d.layers[name] = Layer(name, color=base.color if base else 7, ltype=base.ltype if base else "Continuous")

        self._apply(add)
        row = list(self.cv.doc.layers).index(name)
        self.table.setCurrentCell(row, 1)
        self.table.editItem(self.table.item(row, 1))

    def delete_layer(self):
        name = self._name(self.table.currentRow())
        doc = self.cv.doc
        if not name:
            return
        used = any(e.layer == name for e in doc.entities) or any(e.layer == name for b in doc.blocks.values() for e in b.entities)
        if name == "0" or name == doc.current_layer or used:
            QMessageBox.information(self, "圖層", "無法刪除：圖層 0、目前圖層，以及含有物件的圖層都不能刪除。")
            return
        self._apply(lambda d: d.layers.pop(name, None))

    def set_current(self):
        name = self._name(self.table.currentRow())
        doc = self.cv.doc
        if not name:
            return
        if doc.layers[name].frozen:
            QMessageBox.information(self, "圖層", "凍結的圖層不能設為目前圖層。")
            return
        self._apply(lambda d: setattr(d, "current_layer", name))


# ================================================================ 性質選項板
def _f(attr, label, ro=False):
    return (label, attr, "ro" if ro else "float")


def _solid_dims(e):
    b=e.bbox3d()
    return (0.0,0.0,0.0) if not b else (b[3]-b[0],b[4]-b[1],b[5]-b[2])

def _solid_volume(e):
    try:
        from .io_utils import _cq_shape_from_solid
        return float(_cq_shape_from_solid(e,1.0).Volume())
    except Exception:
        # signed tetrahedron fallback for closed triangle meshes
        vol=0.0
        for face in e.faces:
            ids=[int(i) for i in face if 0<=int(i)<len(e.vertices)]
            if len(ids)<3:continue
            a=e.vertices[ids[0]]
            for k in range(1,len(ids)-1):
                b=e.vertices[ids[k]];c=e.vertices[ids[k+1]]
                vol += (a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6.0
        return abs(vol)

GEOMETRY = {
    Line: [_f("x1", "起點 X"), _f("y1", "起點 Y"), _f("x2", "終點 X"), _f("y2", "終點 Y"),
           ("長度", lambda e: e.length(), "ro"), ("角度", lambda e: G.ang((e.x1, e.y1), (e.x2, e.y2)), "ro")],
    Circle: [_f("cx", "中心點 X"), _f("cy", "中心點 Y"), _f("r", "半徑"), ("直徑", lambda e: e.r * 2, "ro"),
             ("圓周", lambda e: TWO_PI * e.r, "ro"), ("面積", lambda e: math.pi * e.r ** 2, "ro")],
    Arc: [_f("cx", "中心點 X"), _f("cy", "中心點 Y"), _f("r", "半徑"), _f("a0", "起始角度"), _f("a1", "終止角度"),
          ("弧長", lambda e: e.length(), "ro")],
    Polyline: [("閉合", "closed", "bool"), ("頂點數", lambda e: len(e.pts), "ro"), ("長度", lambda e: e.length(), "ro"),
               ("面積", lambda e: e.area(), "ro")],
    Ellipse: [_f("cx", "中心點 X"), _f("cy", "中心點 Y"), ("長軸半徑", lambda e: math.hypot(e.mx, e.my), "ro"),
              _f("ratio", "半徑比")],
    Spline: [("擬合點數", lambda e: len(e.fit), "ro"), ("控制點數", lambda e: len(e.ctrl), "ro")],
    Point: [_f("x", "位置 X"), _f("y", "位置 Y")],
    Text: [("內容", "text", "str"), _f("height", "高度"), _f("rot", "旋轉"), _f("x", "位置 X"), _f("y", "位置 Y"),
           ("水平對正", "halign", ["左", "中", "右"]), ("垂直對正", "valign", ["基準線", "下", "中", "上"])],
    MText: [("內容", "text", "mstr"), _f("height", "文字高度"), _f("rot", "旋轉"), _f("width", "寬度"),
            _f("x", "位置 X"), _f("y", "位置 Y")],
    Hatch: [("樣式", "pattern", sorted(HATCH_PATTERNS)), _f("scale", "比例"), _f("angle", "角度"),
            ("面積", lambda e: e.area(), "ro")],
    Dim: [("文字取代", "text", "str"), ("量測值", lambda e: e.label(), "ro"), _f("th", "文字高度"), _f("asz", "箭頭大小"),
          ("精確度", "dec", "int")],
    Insert: [("名稱", lambda e: e.name, "ro"), _f("x", "位置 X"), _f("y", "位置 Y"), _f("sx", "比例 X"),
             _f("sy", "比例 Y"), _f("rot", "旋轉")],
    Array: [("類型", lambda e: "矩形" if e.mode.upper() == "RECT" else "環形", "ro"),
            ("列數", "rows", "int"), ("欄數", "cols", "int"), _f("dx", "欄間距"), _f("dy", "列間距"),
            ("項目數", "count", "int"), _f("fill", "填滿角度"), ("旋轉項目", "rotate_items", "bool"),
            ("來源物件數", lambda e: len(e.source), "ro")],
    XLine: [_f("x", "基準點 X"), _f("y", "基準點 Y"), _f("dx", "方向 X"), _f("dy", "方向 Y")],
    Solid3D: [("實體類型", lambda e:e.shape, "ro"),
              ("X 尺寸", lambda e:_solid_dims(e)[0], "ro"), ("Y 尺寸", lambda e:_solid_dims(e)[1], "ro"),
              ("Z 尺寸", lambda e:_solid_dims(e)[2], "ro"), ("體積", _solid_volume, "ro"),
              ("頂點數", lambda e:len(e.vertices), "ro"), ("面數", lambda e:len(e.faces), "ro"),
              ("精確 BREP", lambda e:"是" if bool(getattr(e,"brep_b64", "")) else "否", "ro")],
}
COLOR_CHOICES = [BYLAYER, BYBLOCK, 1, 2, 3, 4, 5, 6, 7, 8, 9]


class PropertiesPalette(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        self.head = QLabel("無選取")
        self.head.setStyleSheet("font-weight:bold;padding:4px;")
        v.addWidget(self.head)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["性質", "值"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.itemChanged.connect(self.on_item)
        v.addWidget(self.table)
        self._busy = False
        self.setMinimumWidth(250)

    @property
    def cv(self):
        return self.main.canvas

    # ---- 建表
    def _section(self, title):
        r = self.table.rowCount()
        self.table.insertRow(r)
        it = QTableWidgetItem(title)
        it.setFlags(Qt.ItemFlag.ItemIsEnabled)
        it.setBackground(QColor(48, 56, 69))
        f = it.font()
        f.setBold(True)
        it.setFont(f)
        self.table.setItem(r, 0, it)
        self.table.setSpan(r, 0, 1, 2)

    def _row(self, label, value, key=None, editable=False):
        r = self.table.rowCount()
        self.table.insertRow(r)
        a = QTableWidgetItem(label)
        a.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(r, 0, a)
        b = QTableWidgetItem(value)
        b.setFlags((Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable) if editable
                   else Qt.ItemFlag.ItemIsEnabled)
        if not editable:
            b.setForeground(QColor(150, 160, 172))
        b.setData(Qt.ItemDataRole.UserRole, key)
        self.table.setItem(r, 1, b)
        return r

    def _combo(self, label, items, current, slot, icons=None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        a = QTableWidgetItem(label)
        a.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(r, 0, a)
        cb = QComboBox()
        for i, s in enumerate(items):
            if icons and icons[i] is not None:
                cb.addItem(icons[i], s)
            else:
                cb.addItem(s)
        if current in items:
            cb.setCurrentIndex(items.index(current))
        else:
            cb.insertItem(0, current)
            cb.setCurrentIndex(0)
        cb.activated.connect(lambda i, cb=cb: slot(cb.currentText()))
        self.table.setCellWidget(r, 1, cb)

    def _common(self, sel, getter, show=str):
        vals = {getter(e) for e in sel}
        return show(next(iter(vals))) if len(vals) == 1 else MULTI

    def refresh(self):
        if not self.isVisible():
            return
        cv = self.cv
        doc = cv.doc
        sel = cv.selection
        self._busy = True
        self.table.setRowCount(0)
        self.table.clearSpans()
        prec = int(doc.vars.get("LUPREC", 4))
        num = lambda v: fmt(v, prec)
        layers = list(doc.layers)
        cnames = [color_name(c) for c in COLOR_CHOICES] + ["選取顏色..."]
        cicons = [swatch(aci_rgb(c)) if 0 < c < 256 else swatch((120, 128, 138)) for c in COLOR_CHOICES] + [None]
        lts = ["ByLayer", "ByBlock"] + sorted(doc.linetypes, key=lambda s: (s != "Continuous", s))
        lws = [LW_BYLAYER, LW_DEFAULT] + LINEWEIGHTS
        if not sel:
            self.head.setText("無選取")
            self._section("一般（目前設定）")
            self._combo("顏色", cnames, color_name(doc.vars["CECOLOR"]), lambda s: self._set_var_color(s), cicons)
            self._combo("圖層", layers, doc.current_layer, lambda s: self.main.set_current_layer(s))
            self._combo("線型", lts, doc.vars["CELTYPE"], lambda s: self._set_var("CELTYPE", s))
            self._combo("線粗", [lw_name(x) for x in lws], lw_name(doc.vars["CELWEIGHT"]),
                        lambda s: self._set_var("CELWEIGHT", lws[[lw_name(x) for x in lws].index(s)]))
            self._row("線型比例", num(doc.vars["LTSCALE"]), ("var", "LTSCALE"), True)
            self._section("註解")
            self._row("文字高度", num(doc.vars["TEXTSIZE"]), ("var", "TEXTSIZE"), True)
            self._row("標註比例", num(doc.vars["DIMSCALE"]), ("var", "DIMSCALE"), True)
            self._row("標註文字高度", num(doc.vars["DIMTXT"]), ("var", "DIMTXT"), True)
            self._row("標註箭頭大小", num(doc.vars["DIMASZ"]), ("var", "DIMASZ"), True)
            self._row("標註精確度", str(doc.vars["DIMDEC"]), ("var", "DIMDEC"), True)
            self._section("圖面")
            self._row("物件數", str(len(doc.entities)))
            self._row("圖層數", str(len(doc.layers)))
            self._row("圖塊數", str(len(doc.blocks)))
            self._busy = False
            return
        types = {type(e) for e in sel}
        self.head.setText("%s (%d)" % (sel[0].NAME if len(types) == 1 else "全部", len(sel)))
        self._section("一般")
        self._combo("顏色", cnames, self._common(sel, lambda e: e.color, color_name), self._set_color, cicons)
        self._combo("圖層", layers, self._common(sel, lambda e: e.layer), lambda s: self._set("layer", s))
        self._combo("線型", lts, self._common(sel, lambda e: e.ltype), lambda s: self._set("ltype", s))
        self._row("線型比例", self._common(sel, lambda e: e.lts, num), ("attr", "lts", "float"), True)
        self._combo("線粗", [lw_name(x) for x in lws], self._common(sel, lambda e: e.lw, lw_name),
                    lambda s: self._set("lw", lws[[lw_name(x) for x in lws].index(s)]))
        if len(types) == 1:
            spec = GEOMETRY.get(next(iter(types)), [])
            if spec:
                self._section("幾何圖形" if next(iter(types)) not in (Text, MText, Dim, Hatch) else "內容")
            for label, attr, kind in spec:
                if callable(attr):
                    v = self._common(sel, attr, lambda x: num(x) if isinstance(x, float) else str(x))
                    self._row(label, v)
                elif isinstance(kind, list):
                    cur = self._common(sel, lambda e: getattr(e, attr),
                                       lambda x: kind[x] if isinstance(x, int) and x < len(kind) else str(x))
                    self._combo(label, kind, cur, lambda s, attr=attr, kind=kind: self._set(
                        attr, kind.index(s) if isinstance(getattr(sel[0], attr), int) else s))
                elif kind == "bool":
                    cur = self._common(sel, lambda e: getattr(e, attr), lambda x: "是" if x else "否")
                    self._combo(label, ["是", "否"], cur, lambda s, attr=attr: self._set(attr, s == "是"))
                else:
                    show = (lambda x: num(x)) if kind == "float" else (lambda x: str(x).replace("\n", "\\P"))
                    self._row(label, self._common(sel, lambda e: getattr(e, attr), show), ("attr", attr, kind), True)
        self._busy = False

    # ---- 套用
    def _set(self, attr, value):
        if value == MULTI:
            return
        self.cv.modify_selected(lambda e: e.clone(**{attr: value}) if hasattr(e, attr) else e)

    def _set_color(self, s):
        if s == MULTI:
            return
        if s == "選取顏色...":
            c = ColorDialog.get(self, 7)
            if c is None:
                self.refresh()
                return
        else:
            c = COLOR_CHOICES[[color_name(x) for x in COLOR_CHOICES].index(s)]
        self._set("color", c)

    def _set_var(self, name, value):
        cv = self.cv
        cv.doc.push_undo()
        cv.doc.vars[name] = value
        cv.changed()

    def _set_var_color(self, s):
        if s == "選取顏色...":
            c = ColorDialog.get(self, 7)
            if c is None:
                self.refresh()
                return
        else:
            c = COLOR_CHOICES[[color_name(x) for x in COLOR_CHOICES].index(s)]
        self._set_var("CECOLOR", c)

    def on_item(self, it):
        if self._busy or it.column() != 1:
            return
        key = it.data(Qt.ItemDataRole.UserRole)
        if not key:
            return
        text = it.text().strip()
        try:
            if key[0] == "var":
                cur = self.cv.doc.vars[key[1]]
                v = int(float(text)) if isinstance(cur, int) else float(text)
                if key[1] != "DIMDEC" and v <= 0:
                    raise ValueError
                self._set_var(key[1], v)
            else:
                _, attr, kind = key
                if text == MULTI:
                    raise ValueError
                if kind == "float":
                    v = float(text)
                    if attr in ("r", "height", "th", "asz", "scale", "sx", "sy", "lts") and v <= 0:
                        raise ValueError
                    if attr == "ratio" and not 0 < v <= 1:
                        raise ValueError
                elif kind == "int":
                    iv = int(float(text))
                    if attr == "dec":
                        v = max(0, min(8, iv))
                    elif attr in ("rows", "cols", "count"):
                        v = max(1, min(10000, iv))
                    else:
                        v = iv
                elif kind == "mstr":
                    v = text.replace("\\P", "\n")
                else:
                    v = it.text()
                self._set(attr, v)
        except ValueError:
            pass
        self.refresh()


# ================================================================ 對話框
class TextDialog(QDialog):
    def __init__(self, parent, title, text="", height=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 260)
        v = QVBoxLayout(self)
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(text)
        v.addWidget(self.edit)
        self.h = None
        if height is not None:
            row = QHBoxLayout()
            row.addWidget(QLabel("文字高度:"))
            self.h = QDoubleSpinBox()
            self.h.setDecimals(4)
            self.h.setRange(0.0001, 1e6)
            self.h.setValue(height)
            row.addWidget(self.h)
            row.addStretch()
            v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.edit.setFocus()


class DraftingSettings(QDialog):
    """製圖設定：鎖點與格線、極座標追蹤、物件鎖點。"""

    def __init__(self, parent, s, tab=2):
        super().__init__(parent)
        from .canvas import SNAP_NAMES, SNAP_ORDER
        self.s = s
        self.setWindowTitle("製圖設定")
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs)
        # 鎖點與格線
        w = QWidget()
        g = QGridLayout(w)
        self.c_snap = QCheckBox("鎖點打開 (F9)")
        self.c_snap.setChecked(s.snap)
        self.c_grid = QCheckBox("格線打開 (F7)")
        self.c_grid.setChecked(s.grid)
        self.snap_sz = QDoubleSpinBox()
        self.grid_sz = QDoubleSpinBox()
        for sp, val in ((self.snap_sz, s.snap_size), (self.grid_sz, s.grid_size)):
            sp.setDecimals(4)
            sp.setRange(0.0001, 1e6)
            sp.setValue(val)
        g.addWidget(self.c_snap, 0, 0)
        g.addWidget(self.c_grid, 0, 2)
        g.addWidget(QLabel("鎖點間距:"), 1, 0)
        g.addWidget(self.snap_sz, 1, 1)
        g.addWidget(QLabel("格線間距:"), 1, 2)
        g.addWidget(self.grid_sz, 1, 3)
        g.setRowStretch(2, 1)
        tabs.addTab(w, "鎖點與格線")
        # 極座標追蹤
        w = QWidget()
        g = QGridLayout(w)
        self.c_polar = QCheckBox("極座標追蹤打開 (F10)")
        self.c_polar.setChecked(s.polar)
        self.c_otrack = QCheckBox("物件鎖點追蹤打開 (F11)")
        self.c_otrack.setChecked(s.otrack)
        self.inc = QComboBox()
        self.incs = [90.0, 60.0, 45.0, 30.0, 22.5, 18.0, 15.0, 10.0, 5.0]
        self.inc.addItems([fmt(x, 1) for x in self.incs])
        if s.polar_inc in self.incs:
            self.inc.setCurrentIndex(self.incs.index(s.polar_inc))
        g.addWidget(self.c_polar, 0, 0, 1, 2)
        g.addWidget(self.c_otrack, 1, 0, 1, 2)
        g.addWidget(QLabel("追蹤增量角度:"), 2, 0)
        g.addWidget(self.inc, 2, 1)
        g.setRowStretch(3, 1)
        tabs.addTab(w, "極座標追蹤")
        # 物件鎖點
        w = QWidget()
        g = QGridLayout(w)
        self.c_osnap = QCheckBox("物件鎖點打開 (F3)")
        self.c_osnap.setChecked(s.osnap)
        g.addWidget(self.c_osnap, 0, 0, 1, 2)
        box = QGroupBox("物件鎖點模式")
        bg = QGridLayout(box)
        self.modes = {}
        for i, k in enumerate(SNAP_ORDER):
            c = QCheckBox(SNAP_NAMES[k])
            c.setChecked(k in s.modes)
            self.modes[k] = c
            bg.addWidget(c, i % 6, i // 6)
        g.addWidget(box, 1, 0, 1, 2)
        b1, b2 = QPushButton("全部選取"), QPushButton("全部清除")
        b1.clicked.connect(lambda: [c.setChecked(True) for c in self.modes.values()])
        b2.clicked.connect(lambda: [c.setChecked(False) for c in self.modes.values()])
        g.addWidget(b1, 2, 0)
        g.addWidget(b2, 2, 1)
        tabs.addTab(w, "物件鎖點")
        tabs.setCurrentIndex(tab)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def apply(self):
        s = self.s
        s.snap, s.grid, s.polar, s.osnap, s.otrack = (self.c_snap.isChecked(), self.c_grid.isChecked(), self.c_polar.isChecked(),
                                                      self.c_osnap.isChecked(), self.c_otrack.isChecked())
        s.snap_size, s.grid_size = self.snap_sz.value(), self.grid_sz.value()
        s.polar_inc = self.incs[self.inc.currentIndex()]
        s.modes = {k for k, c in self.modes.items() if c.isChecked()}
        if s.polar:
            s.ortho = False


class UnitsDialog(QDialog):
    """圖面單位設定；對應 DXF $INSUNITS。"""

    def __init__(self, parent, doc):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("圖面單位")
        g = QGridLayout(self)
        self.units = QComboBox()
        self.codes = sorted(UNIT_NAMES)
        self.units.addItems([UNIT_NAMES[k] for k in self.codes])
        code = int(doc.vars.get("INSUNITS", 4))
        if code in self.codes:
            self.units.setCurrentIndex(self.codes.index(code))
        self.prec = QSpinBox()
        self.prec.setRange(0, 8)
        self.prec.setValue(int(doc.vars.get("LUPREC", 4)))
        g.addWidget(QLabel("插入比例單位:"), 0, 0)
        g.addWidget(self.units, 0, 1)
        g.addWidget(QLabel("顯示精度 (小數位):"), 1, 0)
        g.addWidget(self.prec, 1, 1)
        note = QLabel("單位設定不會自動縮放現有幾何；它用於圖面語意、DXF 匯入/匯出與後續插入比例。")
        note.setWordWrap(True)
        g.addWidget(note, 2, 0, 1, 2)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        g.addWidget(bb, 3, 0, 1, 2)

    def apply(self):
        self.doc.vars["INSUNITS"] = self.codes[self.units.currentIndex()]
        self.doc.vars["LUPREC"] = self.prec.value()



class PlotDialog(QDialog):
    SCALES = [("佈滿圖紙", None), ("1:1", 1.0), ("1:2", 2.0), ("1:5", 5.0), ("1:10", 10.0), ("1:20", 20.0),
              ("1:50", 50.0), ("1:100", 100.0), ("1:200", 200.0), ("1:500", 500.0), ("2:1", 0.5), ("5:1", 0.2)]

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("出圖 - 模型")
        g = QGridLayout(self)
        self.dev = QComboBox()
        self.dev.addItems(["PDF 檔案", "系統印表機..."])
        self.paper = QComboBox()
        self.paper.addItems(["A4", "A3", "A2", "A1", "A0"])
        self.paper.setCurrentText("A3")
        self.orient = QComboBox()
        self.orient.addItems(["橫式", "直式"])
        self.area = QComboBox()
        self.area.addItems(["實際範圍", "顯示"])
        self.scale = QComboBox()
        self.scale.addItems([s for s, _ in self.SCALES])
        self.mono = QCheckBox("單色出圖 (monochrome.ctb)")
        self.mono.setChecked(True)
        self.lw = QCheckBox("出圖物件線粗")
        self.lw.setChecked(True)
        rows = [("印表機/繪圖機:", self.dev), ("圖紙大小:", self.paper), ("圖面方位:", self.orient),
                ("出圖區域:", self.area), ("出圖比例 (1 mm = 幾個圖面單位):", self.scale)]
        for i, (lab, w) in enumerate(rows):
            g.addWidget(QLabel(lab), i, 0)
            g.addWidget(w, i, 1)
        g.addWidget(self.mono, len(rows), 0, 1, 2)
        g.addWidget(self.lw, len(rows) + 1, 0, 1, 2)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        g.addWidget(bb, len(rows) + 2, 0, 1, 2)

    def options(self):
        return dict(paper=self.paper.currentText(), landscape=self.orient.currentIndex() == 0,
                    units_per_mm=self.SCALES[self.scale.currentIndex()][1], mono=self.mono.isChecked(),
                    lineweights=self.lw.isChecked())
