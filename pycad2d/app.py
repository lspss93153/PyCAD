# SPDX-License-Identifier: GPL-3.0-only
"""主視窗：功能區、圖面頁籤、指令行、狀態列、選項板，以及檔案／出圖等介面層指令。"""
import os
import sys
from collections.abc import Sequence
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPainter
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox,
                               QDockWidget, QStatusBar, QLabel, QTabBar, QStackedWidget, QToolButton, QToolBar, QMenu,
                               QInputDialog, QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QDialogButtonBox,
                               QSizePolicy, QComboBox)
from . import __version__
from . import commands as C
from . import geometry as G
from . import io_utils as IO
from . import render as R
from .canvas import CadCanvas, Settings, SNAP_NAMES, SNAP_ORDER
from .icons import icon, swatch
from .model import (Document, Text, MText, Dim, Insert, Array, Solid3D, aci_rgb, color_name, BYLAYER, LW_BYLAYER, UNIT_NAMES)
from .panels import (LayerManager, PropertiesPalette, DraftingSettings, UnitsDialog, PlotDialog, TextDialog, ColorDialog)
from .ribbon import (Ribbon, PropCombo, CommandLine, status_button, color_entries, lw_entries)

APP = "PyCAD"

STYLE = """
QMainWindow, QDialog { background:#3b4453; }
QWidget { color:#d9dee4; font-size:12px; }
QMenuBar { background:#262d38; color:#d9dee4; }
QMenuBar::item { padding:4px 9px; background:transparent; }
QMenuBar::item:selected, QMenu::item:selected { background:#2d6fb4; }
QMenu { background:#303845; border:1px solid #1d222b; }
QMenu::item { padding:5px 26px 5px 22px; }
QMenu::separator { height:1px; background:#4a5464; margin:3px 6px; }
QToolBar { background:#262d38; border:0; spacing:1px; padding:1px 4px; }
QToolButton { background:transparent; border:1px solid transparent; border-radius:2px; padding:1px 3px; color:#d9dee4; }
QToolButton:hover { background:#4e5a6e; border-color:#6a7890; }
QToolButton:pressed { background:#2d6fb4; }
QToolButton:checked { background:#2d6fb4; border-color:#5a9be0; }
#ribbon::pane { border:0; background:#3b4453; }
#ribbon > QTabBar { background:#262d38; }
#ribbon QTabBar::tab { background:#262d38; color:#c3cad3; padding:4px 14px; border:0; min-width:40px; }
#ribbon QTabBar::tab:selected { background:#3b4453; color:#ffffff; }
#ribbon QTabBar::tab:hover:!selected { background:#333c4a; }
#ribbonPanel { background:#3b4453; border-right:1px solid #2a313c; }
#ribbonTitle { background:#303845; color:#aeb7c2; font-size:11px; }
#fileTabs { background:#262d38; }
#fileTabs QTabBar::tab { background:#303845; color:#c3cad3; padding:4px 10px; border:1px solid #1d222b; border-bottom:0; margin-right:1px; }
#fileTabs QTabBar::tab:selected { background:#4a5568; color:#ffffff; }
QComboBox { background:#2a313c; border:1px solid #566176; padding:1px 4px; }
QComboBox:hover { border-color:#7fa9dc; }
QComboBox QAbstractItemView { background:#2a313c; selection-background-color:#2d6fb4; border:1px solid #1d222b; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox { background:#222933; border:1px solid #566176; selection-background-color:#2d6fb4; }
#cmdFrame { background:#262d38; border-top:1px solid #1d222b; }
#cmdLog { background:#212830; border:0; color:#aeb7c2; font-family:"DejaVu Sans Mono","Consolas","Noto Sans Mono CJK TC",monospace; font-size:12px; }
#cmdEdit { background:#2f3742; border:1px solid #566176; padding:3px; font-size:13px; }
#cmdPrompt { color:#e8edf2; font-size:13px; }
QStatusBar { background:#303845; border-top:1px solid #1d222b; }
QStatusBar::item { border:0; }
QDockWidget { titlebar-close-icon:none; }
QDockWidget::title { background:#303845; padding:4px; }
QTableWidget { background:#2f3742; gridline-color:#414b5a; border:1px solid #1d222b; alternate-background-color:#333c4a; }
QTableWidget::item:selected { background:#2d6fb4; }
QHeaderView::section { background:#303845; border:0; border-right:1px solid #1d222b; padding:3px; }
QPushButton { background:#4a5568; border:1px solid #677389; padding:4px 12px; border-radius:2px; }
QPushButton:hover { background:#586580; }
QPushButton:pressed { background:#2d6fb4; }
QGroupBox { border:1px solid #566176; margin-top:8px; padding-top:8px; }
QGroupBox::title { subcontrol-origin:margin; left:8px; }
QTabWidget::pane { border:1px solid #566176; }
QTabBar::tab { background:#303845; padding:5px 12px; }
QTabBar::tab:selected { background:#4a5568; }
QToolTip { background:#f4f6f8; color:#1c232c; border:1px solid #76828f; }
QScrollBar:vertical { background:#2a313c; width:11px; }
QScrollBar::handle:vertical { background:#5a667a; min-height:20px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
"""

UI_ALIASES = {"QSAVE": "SAVE", "EXIT": "QUIT", "PRINT": "PLOT", "LA": "LAYER", "PR": "PROPERTIES", "CH": "PROPERTIES",
              "MO": "PROPERTIES", "PROPS": "PROPERTIES", "OS": "DSETTINGS", "OSNAP": "DSETTINGS", "DS": "DSETTINGS",
              "SE": "DSETTINGS", "UN": "UNITS", "U": "UNDO", "ED": "DDEDIT", "TEXTEDIT": "DDEDIT", "COL": "COLOR", "?": "HELP",
              "ZE": "ZOOMEXT", "DXFOUT": "EXPORTDXF", "EXPORT": "EXPORTDXF", "AI_SELALL": "SELECTALL",
              "SEISO": "VIEWSEISO", "SWISO": "VIEWSWISO", "NEISO": "VIEWNEISO", "NWISO": "VIEWNWISO",
              "TOP": "VIEWTOP", "FRONT": "VIEWFRONT", "RIGHT": "VIEWRIGHT",
              "3DO": "3DORBIT", "ORBIT": "3DORBIT", "STLOUT": "EXPORTSTL", "STEPOUT": "EXPORTSTEP",
              "OBJOUT":"EXPORTOBJ", "PLYOUT":"EXPORTPLY", "OFFOUT":"EXPORTOFF", "3MFOUT":"EXPORT3MF", "GLTFOUT":"EXPORTGLTF",
              "VPORTS":"VPORTS4", "4V":"VPORTS4", "DUCS":"DYN_UCS"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.last_command = None
        self.clip = None
        self.counter = 0
        # Do not force a 1500x920 window on Linux laptops.  Pick a sane initial
        # size and clamp it to the desktop's available work area once QApplication
        # exists.  The window remains fully resizable after this.
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            target_w = min(1500, max(800, int(avail.width() * 0.92)))
            target_h = min(920, max(600, int(avail.height() * 0.90)))
            self.resize(target_w, target_h)
        else:
            self.resize(1200, 760)
        self.setMinimumSize(640, 480)
        self.setStyleSheet(STYLE)
        self.ui_commands = {
            "NEW": self.new_file, "OPEN": self.open_file, "SAVE": self.save_file, "SAVEAS": self.save_as,
            "CLOSE": lambda: self.close_tab(self.tabs.currentIndex()), "QUIT": self.close,
            "PLOT": self.plot, "EXPORTPDF": lambda: self.export("pdf"), "EXPORTSVG": lambda: self.export("svg"),
            "EXPORTPNG": lambda: self.export("png"), "EXPORTDXF": lambda: self.export("dxf"),
            "EXPORTSTL": lambda: self.export("stl"), "EXPORTSTEP": lambda: self.export("step"),
            "EXPORTOBJ": lambda: self.export("obj"),
            "EXPORTPLY": lambda: self.export("ply"), "EXPORTOFF": lambda: self.export("off"),
            "EXPORT3MF": lambda: self.export("3mf"), "EXPORTGLTF": lambda: self.export("gltf"), "EXPORTGLB": lambda: self.export("glb"),
            "EXPORTAMF": lambda: self.export("amf"), "EXPORTWRL": lambda: self.export("wrl"), "EXPORTDAE": lambda: self.export("dae"),
            "IMPORT3D": self.import_3d_file,
            "3DORBIT": lambda: self.canvas.start_orbit(),
            "VS2D": lambda: self.canvas.set_visual_style("2DWIREFRAME"),
            "VS3D": lambda: self.canvas.set_visual_style("3DWIREFRAME"),
            "VSSHADED": lambda: self.canvas.set_visual_style("SHADED_EDGES"),
            "VSCONCEPT": lambda: self.canvas.set_visual_style("CONCEPTUAL"),
            "VPORTS4": lambda: self.canvas.toggle_quad_view(),
            "UCS": self.ucs_dialog, "DYN_UCS": lambda: self.canvas.toggle_dynamic_ucs(),
            "LAYER": self.show_layers, "PROPERTIES": self.toggle_properties, "DSETTINGS": self.drafting_settings, "UNITS": self.units_dialog,
            "UNDO": lambda: self.canvas.undo(), "REDO": lambda: self.canvas.redo(),
            "COPYCLIP": self.copy_clip, "CUTCLIP": self.cut_clip, "PASTECLIP": self.paste_clip,
            "SELECTALL": lambda: self.canvas.select_all(), "HELP": self.show_help, "DDEDIT": self.ddedit,
            "COLOR": self.pick_current_color, "ZOOMEXT": lambda: self.canvas.zoom_extents(),
            "ZOOMPREV": lambda: self.canvas.zoom_prev(),
            "VIEWTOP": lambda: self.set_view("TOP"), "VIEWBOTTOM": lambda: self.set_view("BOTTOM"),
            "VIEWFRONT": lambda: self.set_view("FRONT"), "VIEWBACK": lambda: self.set_view("BACK"),
            "VIEWLEFT": lambda: self.set_view("LEFT"), "VIEWRIGHT": lambda: self.set_view("RIGHT"),
            "VIEWSEISO": lambda: self.set_view("SEISO"), "VIEWSWISO": lambda: self.set_view("SWISO"),
            "VIEWNEISO": lambda: self.set_view("NEISO"), "VIEWNWISO": lambda: self.set_view("NWISO"),
        }
        self._build_central()
        self._build_ribbon()
        self._build_menu_and_toolbar()
        self._build_status()
        self._build_docks()
        self.add_document(Document())
        self._set_3d_ribbon_visible(False)
        self.canvas.set_workspace_3d(False)
        QTimer.singleShot(0, lambda: self.canvas.setFocus())

    # ================================================================ 版面
    def _build_central(self):
        c = QWidget()
        self.vbox = QVBoxLayout(c)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(0)
        self.ribbon = Ribbon(self.run_command)
        bar = QWidget()
        bar.setObjectName("fileTabs")
        h = QHBoxLayout(bar)
        h.setContentsMargins(4, 2, 4, 0)
        h.setSpacing(2)
        self.tabs = QTabBar()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(False)
        self.tabs.setExpanding(False)
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.currentChanged.connect(self.on_tab)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        h.addWidget(self.tabs)
        plus = QToolButton()
        plus.setText("＋")
        plus.setToolTip("新圖面")
        plus.setAutoRaise(True)
        plus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        plus.clicked.connect(self.new_file)
        h.addWidget(plus)
        h.addStretch()
        self.vbox.addWidget(bar)
        self.stack = QStackedWidget()
        self.vbox.addWidget(self.stack, 1)
        names = set(C.COMMANDS) | set(self.ui_commands)
        self.cmdline = CommandLine(names)
        self.cmdline.submitted.connect(self.on_submit)
        self.cmdline.cancelled.connect(self.on_escape)
        self.cmdline.keyword.connect(lambda k: (self.canvas.click_keyword(k), self.canvas.setFocus()))
        self.setCentralWidget(c)

    def _build_ribbon(self):
        rb = self.ribbon
        # ---- 常用
        pg = rb.page("常用")
        p = rb.panel(pg, "繪製")
        p.big("LINE", "線")
        p.big("PLINE", "聚合線")
        p.big("CIRCLE", "圓")
        p.big("ARC", "弧")
        p.col([("RECTANG", "矩形"), ("POLYGON", "多邊形"), ("ELLIPSE", "橢圓")])
        p.col([("HATCH", "填充線"), ("SPLINE", "雲形線"), ("XLINE", "建構線")])
        p.col([("POINT", "點"), ("RAY", "射線"), ("REVCLOUD", "修訂雲形")])
        p = rb.panel(pg, "修改")
        p.col([("MOVE", "移動"), ("COPY", "複製"), ("STRETCH", "拉伸")])
        p.col([("ROTATE", "旋轉"), ("MIRROR", "鏡射"), ("SCALE", "比例")])
        p.col([("TRIM", "修剪"), ("EXTEND", "延伸"), ("OFFSET", "偏移")])
        p.col([("FILLET", "圓角"), ("CHAMFER", "倒角"), ("ARRAY", "陣列")])
        p.col([("ERASE", "刪除"), ("EXPLODE", "分解"), ("JOIN", "接合")])
        p.col([("BREAK", "切斷"), ("DIVIDE", "等分"), ("OVERKILL", "刪除重複")])
        p = rb.panel(pg, "註解")
        p.big("MTEXT", "文字")
        p.big("DIM", "標註")
        p.col([("DIMLINEAR", "線性"), ("DIMALIGNED", "對齊"), ("DIMANGULAR", "角度")])
        p.col([("DIMRADIUS", "半徑"), ("DIMDIAMETER", "直徑"), ("MLEADER", "引線")])
        p = rb.panel(pg, "圖層")
        p.big("LAYER", "圖層\n性質")
        self.layer_combo = PropCombo(190)
        self.layer_combo.activated.connect(self.on_layer_combo)
        p.widgets([self.layer_combo])
        p.col([("LAYMCUR", "設為目前"), ("LAYISO", "隔離"), ("LAYUNISO", "取消隔離")])
        p.col([("LAYOFF", "關閉"), ("LAYFRZ", "凍結"), ("LAYLCK", "鎖護")])
        p.col([("LAYON", "全部打開"), ("LAYTHW", "全部解凍"), ("LAYULK", "全部解鎖")])
        p = rb.panel(pg, "圖塊")
        p.big("INSERT", "插入")
        p.col([("BLOCK", "建立"), ("PURGE", "清除")])
        p = rb.panel(pg, "性質")
        p.big("MATCHPROP", "複製\n性質")
        self.color_combo, self.lt_combo, self.lw_combo = PropCombo(140), PropCombo(140), PropCombo(140)
        self.color_combo.activated.connect(self.on_color_combo)
        self.lt_combo.activated.connect(lambda i: self.apply_prop("ltype", "CELTYPE", self.lt_combo.key(i)))
        self.lw_combo.activated.connect(lambda i: self.apply_prop("lw", "CELWEIGHT", self.lw_combo.key(i)))
        p.widgets([self.color_combo, self.lt_combo, self.lw_combo])
        p = rb.panel(pg, "公用程式")
        p.col([("DIST", "距離"), ("AREA", "面積"), ("ID", "點座標")])
        p.col([("LIST", "列示"), ("PROPERTIES", "性質"), ("SELECTSIMILAR", "選取類似", "COPY")])
        p = rb.panel(pg, "剪貼簿")
        p.big("PASTECLIP", "貼上")
        p.col([("COPYCLIP", "複製"), ("CUTCLIP", "剪下")])
        # ---- 插入
        pg = rb.page("插入")
        p = rb.panel(pg, "圖塊")
        p.big("INSERT", "插入")
        p.big("BLOCK", "建立圖塊")
        p.big("EXPLODE", "分解")
        p = rb.panel(pg, "匯入")
        p.big("OPEN", "開啟\nDXF/DWG")
        # ---- 註解
        pg = rb.page("註解")
        p = rb.panel(pg, "文字")
        p.big("MTEXT", "多行文字")
        p.big("TEXT", "單行文字")
        p.col([("DDEDIT", "編輯文字", "MTEXT"), ("TEXTSIZE", "文字高度", "TEXT")])
        p = rb.panel(pg, "標註")
        p.big("DIM", "標註")
        p.col([("DIMLINEAR", "線性"), ("DIMALIGNED", "對齊"), ("DIMANGULAR", "角度")])
        p.col([("DIMRADIUS", "半徑"), ("DIMDIAMETER", "直徑"), ("DIMSCALE", "標註比例", "SCALE")])
        p = rb.panel(pg, "引線")
        p.big("MLEADER", "多重引線")
        p = rb.panel(pg, "填充線與標記")
        p.big("HATCH", "填充線")
        p.big("REVCLOUD", "修訂雲形")
        # ---- 檢視
        pg = rb.page("檢視")
        p = rb.panel(pg, "導覽")
        p.big("ZOOMEXT", "實際範圍")
        p.big("ZOOM", "視窗", "ZOOMWIN")
        p.big("ZOOMPREV", "上一個")
        p.big("REGEN", "重生")
        p = rb.panel(pg, "標準視圖")
        p.big("VIEWSEISO", "東南等角", "VIEWSEISO")
        p.col([("VIEWTOP", "上視", "VIEWTOP"), ("VIEWFRONT", "前視", "VIEWFRONT"), ("VIEWRIGHT", "右視", "VIEWRIGHT")])
        p.col([("VIEWSWISO", "西南等角", "VIEWSWISO"), ("VIEWNEISO", "東北等角", "VIEWNEISO"), ("VIEWNWISO", "西北等角", "VIEWNWISO")])
        p = rb.panel(pg, "選項板")
        p.big("PROPERTIES", "性質")
        p.big("LAYER", "圖層\n性質")
        p = rb.panel(pg, "製圖輔助")
        p.big("DSETTINGS", "製圖設定")
        p.col([("LTSCALE", "線型比例", "TRIM")])
        # ---- 3D 模型（AutoCAD 風格工作區第一階段）
        pg = rb.page("3D 模型")
        p = rb.panel(pg, "實體")
        p.big("BOX", "方塊", "BOX")
        p.big("EXTRUDE", "擠出", "EXTRUDE")
        p.col([("REVOLVE", "旋轉", "ROTATE"), ("SWEEP", "掃掠", "PLINE"), ("LOFT", "混成", "PLINE")])
        p.col([("CYLINDER", "圓柱體", "CYLINDER"), ("CONE", "圓錐體", "CONE"), ("SPHERE", "球體", "SPHERE")])
        p.col([("WEDGE", "楔體", "BOX"), ("PYRAMID", "金字塔", "CONE"), ("TORUS", "圓環", "CIRCLE")])
        p = rb.panel(pg, "布林")
        p.big("UNION", "聯集", "JOIN")
        p.col([("SUBTRACT", "差集", "TRIM"), ("INTERSECT", "交集", "HATCH"), ("SLICE", "切割", "TRIM")])
        p = rb.panel(pg, "3D 修改")
        p.col([("MOVE3D", "3D 移動", "MOVE"), ("PLACE3D", "精準定位", "MOVE"), ("ROTATE3D", "3D 旋轉", "ROTATE"), ("SCALE3D", "3D 比例", "SCALE")])
        p.col([("MIRROR3D", "3D 鏡射", "MIRROR"), ("FILLETEDGE", "邊圓角", "FILLET"), ("CHAMFEREDGE", "邊倒角", "CHAMFER")])
        p = rb.panel(pg, "視圖 / 導覽")
        p.big("3DORBIT", "3D\n軌道", "VIEWSEISO")
        p.col([("VPORTS4", "四視埠", "VIEWTOP"), ("UCS", "UCS", "VIEWSEISO"), ("DYN_UCS", "動態 UCS", "OSNAP")])
        p.col([("VIEWTOP", "上視", "VIEWTOP"), ("VIEWFRONT", "前視", "VIEWFRONT"), ("VIEWRIGHT", "右視", "VIEWRIGHT")])
        p.col([("VIEWSEISO", "東南等角", "VIEWSEISO"), ("VIEWSWISO", "西南等角", "VIEWSWISO"), ("VIEWNEISO", "東北等角", "VIEWNEISO")])
        p = rb.panel(pg, "視覺型式")
        p.big("VSSHADED", "著色\n含邊線", "HATCH")
        p.col([("VS3D", "3D 線架構", "VIEWSEISO"), ("VS2D", "2D 線架構", "VIEWTOP"), ("VSCONCEPT", "概念", "HATCH")])
        p = rb.panel(pg, "修改")
        p.col([("MOVE", "移動"), ("ROTATE", "旋轉"), ("SCALE", "比例")])
        p.col([("COPY", "複製"), ("ERASE", "刪除"), ("PROPERTIES", "性質")])
        p = rb.panel(pg, "導覽")
        p.big("ZOOMEXT", "實際範圍")
        p.col([("ZOOM", "縮放", "ZOOMWIN"), ("ZOOMPREV", "上一個"), ("REGEN", "重生")])
        p = rb.panel(pg, "3D 資料交換")
        p.big("IMPORT3D", "匯入\n3D", "OPEN")
        p.big("EXPORTSTEP", "STEP", "SAVE")
        p.col([("EXPORTSTL", "STL", "SAVE"), ("EXPORTOBJ", "OBJ", "SAVE"), ("EXPORTPLY", "PLY", "SAVE")])
        p.col([("EXPORT3MF", "3MF", "SAVE"), ("EXPORTGLB", "GLB", "SAVE"), ("EXPORTOFF", "OFF", "SAVE")])
        p.col([("EXPORTAMF", "AMF", "SAVE"), ("EXPORTWRL", "VRML", "SAVE"), ("EXPORTDAE", "DAE", "SAVE")])

        # ---- AutoCAD 3D Modeling 風格的專用頁籤（只在 3D 工作區出現）
        pg = rb.page("實體")
        p = rb.panel(pg, "基本實體")
        p.big("BOX", "方塊", "BOX"); p.col([("CYLINDER", "圓柱"), ("CONE", "圓錐"), ("SPHERE", "球體")])
        p.col([("WEDGE", "楔體"), ("PYRAMID", "金字塔"), ("TORUS", "圓環")])
        p = rb.panel(pg, "建立")
        p.big("EXTRUDE", "擠出", "EXTRUDE"); p.col([("REVOLVE", "旋轉"), ("SWEEP", "掃掠"), ("LOFT", "混成")])
        p = rb.panel(pg, "布林")
        p.col([("UNION", "聯集"), ("SUBTRACT", "差集"), ("INTERSECT", "交集"), ("SLICE", "切割")])
        p = rb.panel(pg, "實體編輯")
        p.col([("PLACE3D", "精準定位"), ("FILLETEDGE", "邊圓角"), ("CHAMFEREDGE", "邊倒角"), ("MIRROR3D", "3D 鏡射")])

        pg = rb.page("曲面")
        p = rb.panel(pg, "建立曲面 / 實體特徵")
        p.col([("EXTRUDE", "擠出"), ("REVOLVE", "旋轉"), ("SWEEP", "掃掠"), ("LOFT", "混成")])
        p = rb.panel(pg, "說明")
        p.widgets([QLabel("v0.6.9.2：Precision Gizmo & Workflow Polish")])

        pg = rb.page("網面")
        p = rb.panel(pg, "網格資料")
        p.big("IMPORT3D", "匯入網格", "OPEN")
        p.col([("EXPORTSTL", "STL"), ("EXPORTOBJ", "OBJ"), ("EXPORTPLY", "PLY"), ("EXPORTOFF", "OFF")])
        p.col([("EXPORT3MF", "3MF"), ("EXPORTGLB", "GLB"), ("EXPORTAMF", "AMF"), ("EXPORTDAE", "DAE")])

        pg = rb.page("視覺化")
        p = rb.panel(pg, "視覺型式")
        p.big("VSSHADED", "著色含邊線", "HATCH")
        p.col([("VS2D", "2D 線架構"), ("VS3D", "3D 線架構"), ("VSCONCEPT", "概念")])
        p = rb.panel(pg, "視圖")
        p.big("3DORBIT", "3D 軌道", "VIEWSEISO")
        p.col([("VIEWTOP", "上視"), ("VIEWFRONT", "前視"), ("VIEWRIGHT", "右視"), ("VIEWSEISO", "東南等角")])
        p.col([("VPORTS4", "四視埠"), ("UCS", "UCS"), ("DYN_UCS", "動態 UCS")])

        # ---- 輸出
        pg = rb.page("輸出")
        p = rb.panel(pg, "出圖")
        p.big("PLOT", "出圖")
        p = rb.panel(pg, "匯出")
        p.big("EXPORTPDF", "PDF", "PDF")
        p.big("EXPORTDXF", "DXF", "DXF")
        p.big("EXPORTSVG", "SVG", "SVG")
        p.big("EXPORTPNG", "PNG", "PNG")

    def _build_menu_and_toolbar(self):
        def act(text, cmd, key=None, ic=None):
            a = QAction(text, self)
            if ic:
                a.setIcon(icon(ic))
            if key:
                a.setShortcut(QKeySequence(key))
                a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(lambda _=False, c=cmd: self.run_command(c))
            return a

        mb = self.menuBar()
        spec = [
            ("檔案(&F)", [("新建(&N)", "NEW", "Ctrl+N"), ("開啟(&O)...", "OPEN", "Ctrl+O"), None,
                         ("儲存(&S)", "SAVE", "Ctrl+S"), ("另存新檔(&A)...", "SAVEAS", "Ctrl+Shift+S"), None,
                         ("匯出 PDF...", "EXPORTPDF", None), ("匯出 DXF...", "EXPORTDXF", None),
                         ("匯出 SVG...", "EXPORTSVG", None), ("匯出 PNG...", "EXPORTPNG", None), None,
                         ("匯入 3D 模型...", "IMPORT3D", None), None,
                         ("匯出 STEP 3D...", "EXPORTSTEP", None), ("匯出 STL 3D...", "EXPORTSTL", None),
                         ("匯出 OBJ 3D...", "EXPORTOBJ", None), ("匯出 PLY 3D...", "EXPORTPLY", None),
                         ("匯出 3MF 3D...", "EXPORT3MF", None), ("匯出 glTF/GLB...", "EXPORTGLTF", None), None,
                         ("出圖(&P)...", "PLOT", "Ctrl+P"), None, ("關閉", "CLOSE", "Ctrl+F4"), ("結束(&X)", "QUIT", "Ctrl+Q")]),
            ("編輯(&E)", [("退回(&U)", "UNDO", "Ctrl+Z"), ("重做(&R)", "REDO", "Ctrl+Y"), None,
                         ("剪下(&T)", "CUTCLIP", "Ctrl+X"), ("複製(&C)", "COPYCLIP", "Ctrl+C"),
                         ("貼上(&P)", "PASTECLIP", "Ctrl+V"), None, ("全部選取(&L)", "SELECTALL", "Ctrl+A"),
                         ("刪除", "ERASE", None)]),
            ("檢視(&V)", [("重生(&G)", "REGEN", None), None, ("縮放實際範圍", "ZOOMEXT", None), ("縮放視窗", "ZOOM", None),
                         ("上一個視圖", "ZOOMPREV", None), None,
                         ("上視圖", "VIEWTOP", None), ("前視圖", "VIEWFRONT", None), ("右視圖", "VIEWRIGHT", None),
                         ("東南等角視圖", "VIEWSEISO", None), ("西南等角視圖", "VIEWSWISO", None),
                         ("東北等角視圖", "VIEWNEISO", None), ("西北等角視圖", "VIEWNWISO", None)]),
            ("插入(&I)", [("圖塊(&B)...", "INSERT", None), ("建立圖塊...", "BLOCK", None)]),
            ("格式(&O)", [("圖層(&L)...", "LAYER", None), ("顏色(&C)...", "COLOR", None), ("線型比例", "LTSCALE", None),
                         ("文字高度", "TEXTSIZE", None), ("標註比例", "DIMSCALE", None)]),
            ("工具(&T)", [("性質(&P)", "PROPERTIES", "Ctrl+1"), ("製圖設定(&F)...", "DSETTINGS", None), ("圖面單位(&U)...", "UNITS", None), None,
                         ("距離", "DIST", None), ("面積", "AREA", None), ("點座標", "ID", None), ("列示", "LIST", None), None,
                         ("清除", "PURGE", None), ("刪除重複物件", "OVERKILL", None)]),
            ("繪製(&D)", [(C.DESCRIPTIONS[c], c, None) for c in
                         ("LINE", "RAY", "XLINE", "PLINE", "POLYGON", "RECTANG", "ARC", "CIRCLE", "REVCLOUD", "SPLINE",
                          "ELLIPSE", "POINT", "HATCH", "MTEXT", "TEXT")]),
            ("標註(&N)", [(C.DESCRIPTIONS[c], c, None) for c in
                         ("DIM", "DIMLINEAR", "DIMALIGNED", "DIMRADIUS", "DIMDIAMETER", "DIMANGULAR", "MLEADER")]),
            ("修改(&M)", [(C.DESCRIPTIONS[c], c, None) for c in
                         ("MATCHPROP", "ERASE", "COPY", "MIRROR", "OFFSET", "ARRAY", "MOVE", "ROTATE", "SCALE", "STRETCH",
                          "TRIM", "EXTEND", "BREAK", "JOIN", "CHAMFER", "FILLET", "EXPLODE")]),
            ("說明(&H)", [("指令一覽", "HELP", "F1")]),
        ]
        for title, items in spec:
            m = mb.addMenu(title)
            for it in items:
                if it is None:
                    m.addSeparator()
                else:
                    m.addAction(act(it[0], it[1], it[2], it[1] if it[1] in ("NEW", "OPEN", "SAVE", "PLOT", "UNDO", "REDO") else None))
        tb = QToolBar("快速存取")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        for text, cmd in (("新建", "NEW"), ("開啟", "OPEN"), ("儲存", "SAVE"), ("另存新檔", "SAVEAS"), ("出圖", "PLOT"),
                          ("退回", "UNDO"), ("重做", "REDO")):
            a = QAction(icon(cmd), text, self)
            a.triggered.connect(lambda _=False, c=cmd: self.run_command(c))
            tb.addAction(a)
        tb.addSeparator()
        lab = QLabel("  工作區：")
        lab.setStyleSheet("color:#aeb7c2;")
        tb.addWidget(lab)
        self.workspace_combo = QComboBox()
        self.workspace_combo.addItems(["製圖與註解", "3D 建模"])
        self.workspace_combo.setFixedWidth(130)
        self.workspace_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.workspace_combo.currentTextChanged.connect(self.on_workspace_changed)
        tb.addWidget(self.workspace_combo)
        for w in tb.findChildren(QToolButton):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        # 功能區與指令行放在工具列區，才會橫跨整個視窗（選項板停靠在它們之間）
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        for area, widget, name in ((Qt.ToolBarArea.TopToolBarArea, self.ribbon, "功能區"),
                                   (Qt.ToolBarArea.BottomToolBarArea, self.cmdline, "指令行")):
            bar = QToolBar(name)
            bar.setMovable(False)
            bar.setFloatable(False)
            bar.setStyleSheet("QToolBar{padding:0;border:0;spacing:0;}")
            bar.toggleViewAction().setVisible(False)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            bar.addWidget(widget)
            self.addToolBar(area, bar)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        # 功能鍵
        for key, name in (("F3", "osnap"), ("F6", "ducs"), ("F7", "grid"), ("F8", "ortho"), ("F9", "snap"), ("F10", "polar"),
                          ("F11", "otrack"), ("F12", "dyn")):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _=False, n=name: self.toggle(n))
            self.addAction(a)
        a = QAction(self)
        a.setShortcut(QKeySequence("F2"))
        a.triggered.connect(self.toggle_log)
        self.addAction(a)

    def set_view(self, name):
        self.canvas.set_view_orientation(name, fit=True)
        if hasattr(self, "view_status"):
            labels = {"TOP":"上視", "BOTTOM":"下視", "FRONT":"前視", "BACK":"後視", "LEFT":"左視", "RIGHT":"右視",
                      "SEISO":"東南等角", "SWISO":"西南等角", "NEISO":"東北等角", "NWISO":"西北等角"}
            self.view_status.setText(labels.get(name, name))

    def _set_3d_ribbon_visible(self, visible):
        three_d_tabs = {"3D 模型", "實體", "曲面", "網面", "視覺化"}
        for i in range(self.ribbon.count()):
            if self.ribbon.tabText(i) in three_d_tabs:
                self.ribbon.setTabVisible(i, bool(visible))

    def on_workspace_changed(self, text):
        is3d = text == "3D 建模"
        self._set_3d_ribbon_visible(is3d)
        self.canvas.set_workspace_3d(is3d)
        if is3d:
            # AutoCAD-style 3D workspace: expose 3D ribbon only here.
            self.set_view("SEISO")
            self.canvas.set_visual_style("3DWIREFRAME")
            for i in range(self.ribbon.count()):
                if self.ribbon.tabText(i) == "3D 模型":
                    self.ribbon.setCurrentIndex(i); break
            self.cmdline.append("工作區：3D 建模（v0.6.9.2）｜Shift+中鍵=3D Orbit｜滾輪=游標中心縮放")
        else:
            # Drafting workspace never exposes the 3D modelling ribbon.
            self.set_view("TOP")
            self.canvas.set_visual_style("2DWIREFRAME")
            for i in range(self.ribbon.count()):
                if self.ribbon.tabText(i) == "常用":
                    self.ribbon.setCurrentIndex(i); break
            self.cmdline.append("工作區：製圖與註解")

    def ucs_dialog(self):
        if self.workspace_combo.currentText() != "3D 建模":
            self.cmdline.append("UCS：請先切換到 3D 建模工作區。")
            return
        items = ["世界 (WCS)", "視圖 (View)", "前視平面 (Front)", "右視平面 (Right)", "上視平面 (Top)"]
        cur = getattr(self.canvas, "ucs_mode", "WCS")
        val, ok = QInputDialog.getItem(self, "UCS", "指定使用者座標系：", items, 0, False)
        if ok:
            mode = {"世界 (WCS)":"WCS", "視圖 (View)":"VIEW", "前視平面 (Front)":"FRONT", "右視平面 (Right)":"RIGHT", "上視平面 (Top)":"TOP"}[val]
            self.canvas.set_ucs_mode(mode)

    def _build_status(self):
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)
        self.coord = QLabel("0.0000, 0.0000, 0.0000")
        self.coord.setMinimumWidth(230)
        self.coord.setStyleSheet("padding-left:8px;font-family:'DejaVu Sans Mono','Consolas',monospace;")
        sb.addWidget(self.coord)
        self.fmt_label = QLabel("")
        self.fmt_label.setStyleSheet("color:#aeb7c2;padding:0 8px;")
        sb.addWidget(self.fmt_label)
        model = QToolButton()
        model.setText("模型")
        model.setAutoRaise(True)
        model.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        model.setToolTip("模型空間")
        sb.addPermanentWidget(model)
        self.view_status = QLabel("上視")
        self.view_status.setStyleSheet("color:#aeb7c2;padding:0 6px;")
        self.view_status.setToolTip("目前視圖")
        sb.addPermanentWidget(self.view_status)
        self.toggles = {}
        s = self.settings
        for name, ic, tip in (("ducs", "OSNAP", "動態 UCS (F6)"), ("grid", "GRID", "顯示圖面格線 (F7)"), ("snap", "SNAP", "鎖點模式 (F9)"),
                              ("ortho", "ORTHO", "正交模式 (F8)"), ("polar", "POLAR", "極座標追蹤 (F10)　右鍵：設定角度"),
                              ("osnap", "OSNAP", "物件鎖點 (F3)　右鍵：選擇鎖點模式"), ("otrack", "OTRACK", "物件鎖點追蹤 (F11)"),
                              ("lw", "LWT", "展示線粗"), ("dyn", "DYN", "動態輸入 (F12)")):
            b = status_button(ic, tip, getattr(s, name))
            b.clicked.connect(lambda _=False, n=name: self.toggle(n))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, n=name, b=b: self.toggle_menu(n, b))
            sb.addPermanentWidget(b)
            self.toggles[name] = b

    def _build_docks(self):
        self.props = PropertiesPalette(self)
        self.props_dock = QDockWidget("性質", self)
        self.props_dock.setWidget(self.props)
        self.props_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.props_dock)
        self.props_dock.hide()
        self.props_dock.visibilityChanged.connect(lambda v: v and self.props.refresh())
        self.layers = LayerManager(self)

    # ================================================================ 圖面頁籤
    @property
    def canvas(self):
        return self.stack.currentWidget()

    def canvases(self):
        return [self.stack.widget(i) for i in range(self.stack.count())]

    def add_document(self, doc, name=None):
        if name is None and doc.path is None and doc.source == "PYCAD":
            self.counter += 1
            doc.name = "Drawing%d.pycad" % self.counter
        elif name:
            doc.name = name
        cv = CadCanvas(doc, self.settings, ui=self)
        if hasattr(self, "workspace_combo"):
            cv.set_workspace_3d(self.workspace_combo.currentText() == "3D 建模")
        cv.promptChanged.connect(lambda h, cv=cv: self.on_prompt(cv, h))
        cv.history.connect(lambda t, cv=cv: cv is self.canvas and self.cmdline.append(t))
        cv.coordChanged.connect(lambda x, y, cv=cv: cv is self.canvas and self.coord.setText(
            "%.4f, %.4f, 0.0000" % (x, y)))
        cv.selectionChanged.connect(lambda cv=cv: cv is self.canvas and self.refresh_props())
        cv.docChanged.connect(lambda cv=cv: self.on_doc_changed(cv))
        cv.commandRequested.connect(self.run_command)
        cv.keyTyped.connect(self.cmdline.type_text)
        cv.editRequested.connect(self.edit_entity)
        self.stack.addWidget(cv)
        i = self.tabs.addTab(doc.name)
        self.tabs.setCurrentIndex(i)
        self.stack.setCurrentWidget(cv)
        self.on_tab(i)
        return cv

    def on_tab(self, i):
        if 0 <= i < self.stack.count():
            self.stack.setCurrentIndex(i)
            cv = self.canvas
            self.cmdline.set_prompt(cv.prompt_html(), cv.req is not None and cv.req.kind == "text")
            self.refresh_all()
            cv.setFocus()

    def close_tab(self, i):
        if not (0 <= i < self.stack.count()):
            return False
        cv = self.stack.widget(i)
        if not self.confirm_discard(cv):
            return False
        cv.cancel(silent=True)
        self.stack.removeWidget(cv)
        self.tabs.removeTab(i)
        cv.deleteLater()
        if self.stack.count() == 0:
            self.add_document(Document())
        return True

    def confirm_discard(self, cv):
        if not cv.doc.modified:
            return True
        self.stack.setCurrentWidget(cv)
        self.tabs.setCurrentIndex(self.stack.currentIndex())
        r = QMessageBox.question(self, APP, "要儲存對「%s」所做的變更嗎？" % cv.doc.name,
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save_file()
        return True

    def closeEvent(self, ev):
        for cv in list(self.canvases()):
            if not self.confirm_discard(cv):
                ev.ignore()
                return
        ev.accept()

    # ================================================================ 同步介面狀態
    def refresh_all(self):
        self.refresh_title()
        self.refresh_props()
        self.layers.refresh()

    def refresh_title(self):
        cv = self.canvas
        if cv is None:
            return
        d = cv.doc
        self.setWindowTitle("%s %s - [%s%s]" % (APP, __version__, d.name, " *" if d.modified else ""))
        for i, c in enumerate(self.canvases()):
            self.tabs.setTabText(i, c.doc.name + ("*" if c.doc.modified else ""))
            self.tabs.setTabToolTip(i, c.doc.path or getattr(c.doc, "origin", "") or c.doc.name)
        self.fmt_label.setText("來源格式: %s" % d.source)

    def refresh_props(self):
        """更新功能區上的圖層／顏色／線型／線粗清單與性質選項板。"""
        cv = self.canvas
        if cv is None:
            return
        d = cv.doc
        sel = cv.selection

        def common(get, default):
            if not sel:
                return default
            vals = {get(e) for e in sel}
            return next(iter(vals)) if len(vals) == 1 else None

        ents = []
        for ly in d.layers.values():
            flags = ("" if ly.on else "（關）") + ("（凍）" if ly.frozen else "") + ("（鎖）" if ly.locked else "")
            ents.append((ly.name, ly.name + flags, swatch(aci_rgb(ly.color))))
        self.layer_combo.fill(ents, common(lambda e: e.layer, d.current_layer))
        cur = common(lambda e: e.color, d.vars["CECOLOR"])
        self.color_combo.fill(color_entries(cur), cur)
        lts = [("ByLayer", "ByLayer", None), ("ByBlock", "ByBlock", None)] + \
            [(k, k, None) for k in sorted(d.linetypes, key=lambda s: (s != "Continuous", s))]
        self.lt_combo.fill(lts, common(lambda e: e.ltype, d.vars["CELTYPE"]))
        self.lw_combo.fill(lw_entries(), common(lambda e: e.lw, d.vars["CELWEIGHT"]))
        self.props.refresh()

    def on_doc_changed(self, cv):
        if cv is self.canvas:
            self.refresh_all()
        else:
            self.refresh_title()

    def on_prompt(self, cv, html_text):
        if cv is self.canvas:
            self.cmdline.set_prompt(html_text, cv.req is not None and cv.req.kind == "text")

    def set_current_layer(self, name):
        cv = self.canvas
        d = cv.doc
        if name not in d.layers or name == d.current_layer:
            return
        if d.layers[name].frozen:
            self.cmdline.append("凍結的圖層不能設為目前圖層。")
            self.refresh_props()
            return
        d.push_undo()
        d.current_layer = name
        cv.changed()

    def on_layer_combo(self, i):
        name = self.layer_combo.key(i)
        cv = self.canvas
        if name is None:
            return
        if cv.selection and not cv.busy():
            cv.modify_selected(lambda e: e.clone(layer=name))
        else:
            self.set_current_layer(name)
        cv.setFocus()

    def on_color_combo(self, i):
        key = self.color_combo.key(i)
        if key == "pick":
            key = ColorDialog.get(self, 7)
            if key is None:
                self.refresh_props()
                return
        self.apply_prop("color", "CECOLOR", key)

    def apply_prop(self, attr, var, value):
        cv = self.canvas
        if value is None:
            return
        if cv.selection and not cv.busy():
            cv.modify_selected(lambda e: e.clone(**{attr: value}))
        else:
            cv.doc.vars[var] = value
            self.refresh_props()
        cv.setFocus()

    # ================================================================ 狀態列開關
    def toggle(self, name, value=None):
        s = self.settings
        v = (not getattr(s, name)) if value is None else value
        setattr(s, name, v)
        if name == "ortho" and v:
            s.polar = False
        if name == "polar" and v:
            s.ortho = False
        label = {"ducs":"動態 UCS", "grid": "格線", "snap": "鎖點", "ortho": "正交", "polar": "極座標", "osnap": "物件鎖點", "otrack": "物件鎖點追蹤", "lw": "線粗",
                 "dyn": "動態輸入"}[name]
        self.cmdline.append("<%s %s>" % (label, "打開" if v else "關閉"))
        self.sync_toggles()

    def sync_toggles(self):
        for n, b in self.toggles.items():
            b.setChecked(getattr(self.settings, n))
        for cv in self.canvases():
            cv.invalidate()
        cv = self.canvas
        if cv is not None:
            cv._retarget()

    def toggle_menu(self, name, btn):
        s = self.settings
        m = QMenu(self)
        if name == "osnap":
            for k in SNAP_ORDER:
                a = m.addAction(SNAP_NAMES[k])
                a.setCheckable(True)
                a.setChecked(k in s.modes)
                a.triggered.connect(lambda on, k=k: (s.modes.add(k) if on else s.modes.discard(k)))
            m.addSeparator()
            m.addAction("物件鎖點設定...", lambda: self.drafting_settings(2))
        elif name == "polar":
            for inc in (90.0, 60.0, 45.0, 30.0, 22.5, 18.0, 15.0, 10.0, 5.0):
                a = m.addAction("%g, %g, %g, %g..." % (inc, inc * 2, inc * 3, inc * 4))
                a.setCheckable(True)
                a.setChecked(abs(s.polar_inc - inc) < 1e-9)
                a.triggered.connect(lambda _=False, inc=inc: (setattr(s, "polar_inc", inc), self.toggle("polar", True)))
            m.addSeparator()
            m.addAction("追蹤設定...", lambda: self.drafting_settings(1))
        elif name in ("grid", "snap"):
            m.addAction("格線與鎖點設定...", lambda: self.drafting_settings(0))
        else:
            return
        m.exec(btn.mapToGlobal(btn.rect().topLeft()))

    def drafting_settings(self, tab=2):
        d = DraftingSettings(self, self.settings, tab if isinstance(tab, int) else 2)
        if d.exec():
            d.apply()
            self.sync_toggles()

    def units_dialog(self):
        d = UnitsDialog(self, self.canvas.doc)
        if d.exec():
            d.apply()
            self.canvas.doc.modified = True
            self.canvas.changed()
            self.cmdline.append("圖面單位已設為 %s。" % UNIT_NAMES.get(int(self.canvas.doc.vars.get("INSUNITS", 4)), "無單位"))

    def toggle_log(self):
        big = self.cmdline.log.height() < 100
        self.cmdline.log.setFixedHeight(260 if big else 64)

    # ================================================================ 指令分派
    def on_submit(self, text):
        cv = self.canvas
        if cv.gizmo_numeric_active():
            cv.accept_gizmo_numeric(text)
        elif cv.busy():
            cv.feed_text(text)
        elif text.strip():
            self.run_command(text)
        else:
            self.run_command("")
        if not (cv.req is not None and cv.req.kind == "text"):
            self.canvas.setFocus()

    def on_escape(self):
        if not self.canvas.cancel_gizmo_drag():
            self.canvas.cancel()
        self.canvas.setFocus()

    def run_command(self, text):
        cv = self.canvas
        raw = text.strip()
        name = raw.upper().lstrip("_.'-")
        if not name:
            name = self.last_command
            if not name:
                return
        name = UI_ALIASES.get(name, name)
        name = C.ALIASES.get(name, name)
        if name in self.ui_commands:
            if name not in ("UNDO", "REDO", "ZOOMEXT", "ZOOMPREV", "SELECTALL", "COPYCLIP"):
                cv.cancel(silent=True)
            if name not in ("UNDO", "REDO", "HELP"):
                self.last_command = name
            self.ui_commands[name]()
        elif name in C.COMMANDS:
            self.last_command = name
            cv.start_command(name)
        elif name in cv.doc.vars and not name.startswith("_"):
            self.last_command = name
            cv.start_command(name, C.SETVAR(cv, name))
        else:
            self.cmdline.append("未知的指令「%s」。按 F1 查看指令一覽。" % raw)
        cur = self.canvas
        if cur is not None and not self.cmdline.edit.hasFocus():
            cur.setFocus()

    # ---- 給指令呼叫的介面（canvas.ui）
    def ask_text(self, title, default=""):
        d = TextDialog(self, title, default)
        return d.edit.toPlainText() if d.exec() else None

    def ask_choice(self, title, label, items, current=None):
        s, okk = QInputDialog.getItem(self, title, label, items, items.index(current) if current in items else 0, False)
        return s if okk else None

    def edit_entity(self, e):
        cv = self.canvas
        if isinstance(e, Text):
            s, okk = QInputDialog.getText(self, "編輯文字", "文字:", text=e.text)
            if okk and s:
                cv.set_selection([e])
                cv.modify_selected(lambda x: x.clone(text=s))
        elif isinstance(e, MText):
            d = TextDialog(self, "編輯多行文字", e.text, e.height)
            if d.exec() and d.edit.toPlainText():
                cv.set_selection([e])
                cv.modify_selected(lambda x: x.clone(text=d.edit.toPlainText(), height=d.h.value()))
        elif isinstance(e, Dim):
            s, okk = QInputDialog.getText(self, "編輯標註文字", "文字（留白或 <> 代表量測值）:", text=e.text)
            if okk:
                cv.set_selection([e])
                cv.modify_selected(lambda x: x.clone(text="" if s.strip() == "<>" else s))
        else:
            cv.set_selection([e])
            self.props_dock.show()
            self.props.refresh()

    def ddedit(self):
        cv = self.canvas
        sel = [e for e in cv.selection if isinstance(e, (Text, MText, Dim))]
        if sel:
            self.edit_entity(sel[0])
        else:
            self.cmdline.append("請先點選要編輯的文字或標註（也可以直接在上面按兩下）。")

    def pick_current_color(self):
        c = ColorDialog.get(self, self.canvas.doc.vars["CECOLOR"])
        if c is not None:
            self.apply_prop("color", "CECOLOR", c)

    def show_layers(self):
        self.layers.show()
        self.layers.raise_()
        self.layers.refresh()

    def toggle_properties(self):
        self.props_dock.setVisible(not self.props_dock.isVisible())
        self.props.refresh()

    # ---- 剪貼簿
    def copy_clip(self):
        cv = self.canvas
        if not cv.selection:
            self.cmdline.append("沒有選取物件。")
            return False
        b = cv.doc.extents(cv.selection) or (0, 0, 0, 0)
        names = {e.name for e in cv.selection if isinstance(e, Insert)}
        self.clip = (list(cv.selection), (b[0], b[1]), {n: cv.doc.blocks[n] for n in names if n in cv.doc.blocks})
        self.cmdline.append("已複製 %d 個物件到剪貼簿。" % len(cv.selection))
        return True

    def cut_clip(self):
        cv = self.canvas
        sel = list(cv.selection)
        cv.selection = sel
        if self.copy_clip():
            cv.start_command("ERASE")

    def paste_clip(self):
        cv = self.canvas
        if not self.clip:
            self.cmdline.append("剪貼簿是空的。")
            return
        ents, base, blocks = self.clip
        for n, b in blocks.items():
            if n not in cv.doc.blocks:
                cv.doc.blocks[n] = b
                cv.doc.block_rev += 1
        cv.start_command("PASTECLIP", C.PASTECLIP(cv, ents, base))

    # ================================================================ 檔案
    def new_file(self):
        self.add_document(Document())

    def open_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "選取檔案", "", "所有支援的格式 (*.pycad *.json *.dxf *.dwg);;PyCAD 專案 (*.pycad *.json);;"
                "DXF (*.dxf);;DWG (*.dwg)")
        if not path:
            return None
        ext = os.path.splitext(path)[1].lower()
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            if ext == ".dxf":
                doc = IO.import_dxf(path)
            elif ext == ".dwg":
                doc = IO.import_dwg(path)
            else:
                doc = IO.load_project(path)
                doc.path = path
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "開啟失敗", str(ex))
            return None
        QApplication.restoreOverrideCursor()
        doc.origin = path
        # 如果目前是完全沒動過的空白圖面，就直接取代它
        cur = self.canvas
        replace = (cur is not None and not cur.doc.entities and not cur.doc.modified and cur.doc.path is None
                   and cur.doc.source == "PYCAD")
        if replace:
            i = self.stack.currentIndex()
            self.stack.removeWidget(cur)
            self.tabs.removeTab(i)
            cur.deleteLater()
        cv = self.add_document(doc, os.path.basename(path))
        QTimer.singleShot(0, cv.zoom_extents)
        rep = getattr(doc, "report", None)
        if rep is not None:
            self.cmdline.append("已匯入 %s：%d 個物件、%d 個圖塊、%d 個圖層。" %
                                (os.path.basename(path), rep["count"], rep["blocks"], rep["layers"]))
            if rep["skipped"]:
                self.cmdline.append("  略過不支援的物件：" + "、".join("%s×%d" % kv for kv in sorted(rep["skipped"].items())))
            self.cmdline.append("  原始檔不會被覆寫；按「儲存」會另存成 .pycad，或用「另存新檔」選 DXF 格式。")
        else:
            self.cmdline.append("已開啟 %s" % path)
        return cv

    def save_file(self):
        cv = self.canvas
        d = cv.doc
        if not d.path:
            return self.save_as()
        try:
            IO.save_project(d.path, d)
        except Exception as ex:
            QMessageBox.critical(self, "儲存失敗", str(ex))
            return False
        d.modified = False
        d.name = os.path.basename(d.path)
        self.cmdline.append("已儲存 %s" % d.path)
        self.refresh_title()
        return True

    def save_as(self):
        cv = self.canvas
        d = cv.doc
        filters = ["PyCAD 專案 (*.pycad)"]
        if IO.have_ezdxf():
            filters.append("DXF R2010 (*.dxf)")
        filters.append("DXF R12 (*.dxf)")
        if IO.have_ezdxf() and IO.find_oda():
            filters.append("DWG 2018 (*.dwg)")
        base = os.path.splitext(d.path or getattr(d, "origin", "") or d.name)[0]
        path, flt = QFileDialog.getSaveFileName(self, "圖面另存成", base + ".pycad", ";;".join(filters))
        if not path:
            return False
        try:
            saved_native = flt.startswith("PyCAD")
            has_3d = any(isinstance(e, Solid3D) for e in d.entities)
            if not saved_native and has_3d:
                ans=QMessageBox.warning(self,"3D 資料不會寫入 2D DXF/DWG",
                    "目前 DXF/DWG 匯出器只支援 2D 圖元。圖面含有 3D 實體，若繼續，3D 實體不會出現在匯出的 DXF/DWG。\n\n"
                    "建議改用 STEP 儲存 3D，並用 .pycad 保存可編輯專案。是否仍要繼續匯出？",
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                if ans != QMessageBox.StandardButton.Yes:return False
            if saved_native:
                if not path.lower().endswith(".pycad"):
                    path += ".pycad"
                IO.save_project(path, d)
                d.path, d.name, d.source = path, os.path.basename(path), "PYCAD"
                self.cmdline.append("已儲存 %s" % path)
            elif "DWG" in flt or path.lower().endswith(".dwg"):
                if not path.lower().endswith(".dwg"):
                    path += ".dwg"
                IO.export_dwg(path, d)
                self.cmdline.append("已匯出 DWG：%s" % path)
            else:
                if not path.lower().endswith(".dxf"):
                    path += ".dxf"
                if "R12" in flt:
                    IO.export_dxf_r12(path, d)
                else:
                    IO.export_dxf_2010(path, d)
                self.cmdline.append("已匯出 %s：%s" % (flt.split(" (")[0], path))
        except Exception as ex:
            QMessageBox.critical(self, "儲存失敗", str(ex))
            return False
        # Export is not Save: only the native .pycad path clears the dirty flag.
        if saved_native:
            d.modified = False
        self.refresh_title()
        return True

    def import_3d_file(self):
        d = self.canvas.doc
        path, _ = QFileDialog.getOpenFileName(self, "匯入 3D 模型", "",
            "3D 模型 (*.step *.stp *.stl *.obj *.ply *.off *.3mf *.gltf *.glb *.amf *.dae *.wrl *.vrml);;STEP (*.step *.stp);;STL (*.stl);;OBJ (*.obj);;PLY (*.ply);;OFF (*.off);;3MF (*.3mf);;glTF/GLB (*.gltf *.glb);;AMF (*.amf);;Collada DAE (*.dae);;VRML (*.wrl *.vrml)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.canvas.setUpdatesEnabled(False)
        QApplication.processEvents()
        try:
            ents = IO.import_3d(path, d)
            if not ents:
                raise ValueError("檔案中沒有可匯入的 3D 幾何。")
            d.push_undo()
            for e in ents:
                # inherit current drawing properties while preserving imported geometry
                e.layer = getattr(d, "current_layer", "0")
                d.entities.append(e)
            d.modified = True
            self.canvas.selection = ents
            self.canvas.set_workspace_3d(True)
            if hasattr(self, "workspace_combo"):
                self.workspace_combo.setCurrentText("3D 建模")
            self.canvas.set_view_orientation("SEISO", fit=False)
            # External STL/STEP is normally a tessellated surface.  Opening it in 3D
            # wireframe exposes every triangle and makes a perfectly valid smooth model
            # look corrupt.  Use the existing AutoCAD-style shaded-with-edges visual
            # style on import; users can still explicitly switch to 3D Wireframe.
            self.canvas.set_visual_style("SHADED_EDGES")
            self.canvas.zoom_extents()
            self.refresh_title()
            faces=sum(len(getattr(e,"faces",[]) or []) for e in ents)
            verts=sum(len(getattr(e,"vertices",[]) or []) for e in ents)
            self.cmdline.append("已匯入 3D：%s（%d 個物件，%d 頂點 / %d 面）" % (path,len(ents),verts,faces))
        except Exception as ex:
            QMessageBox.critical(self, "3D 匯入失敗", str(ex))
        finally:
            self.canvas.setUpdatesEnabled(True)
            QApplication.restoreOverrideCursor()
            self.canvas.update()

    def export(self, kind):
        cv = self.canvas
        d = cv.doc
        base = os.path.splitext(d.path or getattr(d, "origin", "") or d.name)[0]
        try:
            if kind == "dxf":
                if any(isinstance(e, Solid3D) for e in d.entities):
                    ans=QMessageBox.warning(self,"3D 資料不會寫入 2D DXF",
                        "DXF 匯出器目前輸出 2D 圖元；3D 實體不會寫入此 DXF。\n\n"
                        "請用 .pycad 保存可編輯專案，並用 STEP 保存 3D 實體。是否仍要匯出 2D DXF？",
                        QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                    if ans != QMessageBox.StandardButton.Yes:return
                flts = (["DXF R2010 (*.dxf)"] if IO.have_ezdxf() else []) + ["DXF R12 (*.dxf)"]
                path, flt = QFileDialog.getSaveFileName(self, "匯出 DXF", base + ".dxf", ";;".join(flts))
                if not path:
                    return
                if not path.lower().endswith(".dxf"):
                    path += ".dxf"
                (IO.export_dxf_r12 if "R12" in flt else IO.export_dxf_2010)(path, d)
            elif kind in ("stl", "step", "obj", "ply", "off", "3mf", "gltf", "glb", "amf", "wrl", "dae"):
                label = {"stl":"STL 3D 模型 (*.stl)", "step":"STEP 3D 模型 (*.step *.stp)", "obj":"Wavefront OBJ (*.obj)",
                         "ply":"PLY 網格 (*.ply)", "off":"OFF 網格 (*.off)", "3mf":"3MF 模型 (*.3mf)",
                         "gltf":"glTF 模型 (*.gltf)", "glb":"GLB 二進位模型 (*.glb)", "amf":"AMF 模型 (*.amf)", "wrl":"VRML97 (*.wrl)", "dae":"Collada DAE (*.dae)"}[kind]
                ext = ".step" if kind == "step" else "." + kind
                path, _ = QFileDialog.getSaveFileName(self, "匯出 " + kind.upper(), base + ext, label)
                if not path:
                    return
                if kind == "step":
                    if not path.lower().endswith((".step", ".stp")): path += ".step"
                    IO.export_step(path, d)
                elif kind == "stl":
                    if not path.lower().endswith(".stl"): path += ".stl"
                    IO.export_stl(path, d)
                elif kind == "obj":
                    if not path.lower().endswith(".obj"): path += ".obj"
                    IO.export_obj(path, d)
                elif kind == "ply":
                    if not path.lower().endswith(".ply"): path += ".ply"
                    IO.export_ply(path, d)
                elif kind == "off":
                    if not path.lower().endswith(".off"): path += ".off"
                    IO.export_off(path, d)
                elif kind == "3mf":
                    if not path.lower().endswith(".3mf"): path += ".3mf"
                    IO.export_3mf(path, d)
                elif kind in ("gltf", "glb"):
                    need = ".glb" if kind == "glb" else ".gltf"
                    if not path.lower().endswith(need): path += need
                    IO.export_gltf(path, d)
                elif kind == "amf":
                    if not path.lower().endswith(".amf"): path += ".amf"
                    IO.export_amf(path, d)
                elif kind == "wrl":
                    if not path.lower().endswith(".wrl"): path += ".wrl"
                    IO.export_wrl(path, d)
                elif kind == "dae":
                    if not path.lower().endswith(".dae"): path += ".dae"
                    IO.export_dae(path, d)
            else:
                label = {"pdf": "PDF (*.pdf)", "svg": "SVG (*.svg)", "png": "PNG 影像 (*.png)"}[kind]
                path, _ = QFileDialog.getSaveFileName(self, "匯出 " + kind.upper(), base + "." + kind, label)
                if not path:
                    return
                if not path.lower().endswith("." + kind):
                    path += "." + kind
                {"pdf": R.export_pdf, "svg": R.export_svg, "png": R.export_png}[kind](d, path)
            self.cmdline.append("已匯出：%s" % path)
        except Exception as ex:
            QMessageBox.critical(self, "匯出失敗", str(ex))

    def plot(self):
        cv = self.canvas
        dlg = PlotDialog(self)
        if not dlg.exec():
            return
        o = dlg.options()
        area = cv.view_rect() if dlg.area.currentIndex() == 1 else None
        try:
            if dlg.dev.currentIndex() == 0:
                base = os.path.splitext(cv.doc.path or cv.doc.name)[0]
                path, _ = QFileDialog.getSaveFileName(self, "出圖到 PDF", base + ".pdf", "PDF (*.pdf)")
                if not path:
                    return
                if not path.lower().endswith(".pdf"):
                    path += ".pdf"
                R.export_pdf(cv.doc, path, area=area, **o)
                self.cmdline.append("已出圖到 %s" % path)
            else:
                from PySide6.QtPrintSupport import QPrinter, QPrintDialog
                from PySide6.QtGui import QPageSize, QPageLayout
                pr = QPrinter(QPrinter.PrinterMode.HighResolution)
                pr.setPageSize(QPageSize(R.PAPER[o["paper"]]))
                pr.setPageOrientation(QPageLayout.Orientation.Landscape if o["landscape"] else QPageLayout.Orientation.Portrait)
                if QPrintDialog(pr, self).exec():
                    p = QPainter(pr)
                    try:
                        rect = pr.pageRect(QPrinter.Unit.DevicePixel)
                        R.plot(cv.doc, p, rect.width(), rect.height(), pr.resolution() / 25.4, area, o["mono"],
                               o["units_per_mm"], o["lineweights"])
                    finally:
                        p.end()
                    self.cmdline.append("已送出列印。")
        except Exception as ex:
            QMessageBox.critical(self, "出圖失敗", str(ex))

    def show_help(self):
        d = QDialog(self)
        d.setWindowTitle("指令一覽")
        d.resize(560, 620)
        v = QVBoxLayout(d)
        v.addWidget(QLabel("在指令行輸入指令或別名後按 Enter／空白鍵。Esc 取消，Enter／空白鍵重複上一個指令。\n"
                           "座標：x,y（絕對）　@dx,dy（相對）　@距離<角度（極座標）　移動滑鼠後直接輸入距離。\n"
                           "滑鼠：滾輪縮放、按住中鍵平移、中鍵按兩下縮放實際範圍；左到右窗選、右到左框選。"))
        rev = {}
        for a, c in list(C.ALIASES.items()) + [(a, c) for a, c in UI_ALIASES.items()]:
            rev.setdefault(c, []).append(a)
        rows = [(c, ", ".join(sorted(rev.get(c, []), key=len)), C.DESCRIPTIONS.get(c, "")) for c in sorted(C.COMMANDS)]
        ui_desc = {"NEW": "新圖面", "OPEN": "開啟", "SAVE": "儲存", "SAVEAS": "另存新檔", "PLOT": "出圖",
                   "LAYER": "圖層性質管理員", "PROPERTIES": "性質選項板", "DSETTINGS": "製圖設定", "UNITS": "圖面單位", "UNDO": "退回",
                   "REDO": "重做", "COPYCLIP": "複製到剪貼簿", "CUTCLIP": "剪下", "PASTECLIP": "貼上",
                   "DDEDIT": "編輯文字", "COLOR": "目前顏色", "EXPORTPDF": "匯出 PDF", "EXPORTDXF": "匯出 DXF",
                   "EXPORTSVG": "匯出 SVG", "EXPORTPNG": "匯出 PNG", "ZOOMEXT": "縮放實際範圍"}
        rows += [(c, ", ".join(sorted(rev.get(c, []), key=len)), ui_desc[c]) for c in sorted(ui_desc)]
        rows.sort()
        t = QTableWidget(len(rows), 3)
        t.setHorizontalHeaderLabels(["指令", "別名", "說明"])
        t.verticalHeader().setVisible(False)
        for r, row in enumerate(rows):
            for c, s in enumerate(row):
                it = QTableWidgetItem(s)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                t.setItem(r, c, it)
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        v.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        d.exec()


def run(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(args)
    app.setApplicationName(APP)
    w = MainWindow()
    w.show()
    for p in args[1:]:
        if os.path.exists(p):
            w.open_file(p)
    return app.exec()
