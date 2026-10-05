# SPDX-License-Identifier: GPL-3.0-only
"""功能區 (Ribbon)、指令行、狀態列元件。"""
from PySide6.QtCore import Qt, Signal, QSize, QStringListModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QTabWidget, QWidget, QFrame, QHBoxLayout, QVBoxLayout, QGridLayout, QToolButton,
                               QLabel, QComboBox, QPlainTextEdit, QLineEdit, QCompleter, QSizePolicy,
                               QScrollArea, QLayout)
from .icons import icon, swatch
from .model import aci_rgb, color_name, lw_name, BYLAYER, BYBLOCK, LW_BYLAYER, LW_DEFAULT, LINEWEIGHTS
from . import commands as C

_REV = {}
for _a, _c in C.ALIASES.items():
    _REV.setdefault(_c, []).append(_a)


def tip_for(cmd, label):
    al = ", ".join(sorted(_REV.get(cmd, []), key=len)[:2])
    return "%s\n%s%s" % (label, cmd, ("  (%s)" % al) if al else "")


class Panel(QFrame):
    def __init__(self, title, run):
        super().__init__()
        self.setObjectName("ribbonPanel")
        self.run = run
        v = QVBoxLayout(self)
        v.setContentsMargins(3, 2, 3, 0)
        v.setSpacing(0)
        body = QWidget()
        self.row = QHBoxLayout(body)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(1)
        v.addWidget(body, 1)
        t = QLabel(title)
        t.setObjectName("ribbonTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setFixedHeight(17)
        v.addWidget(t)

    def _btn(self, cmd, label, ic=None, big=False, text=True):
        b = QToolButton()
        b.setAutoRaise(True)
        b.setIcon(icon(ic or cmd))
        b.setToolTip(tip_for(cmd, label))
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if big:
            b.setText(label)
            b.setIconSize(QSize(30, 30))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setFixedHeight(66)
            b.setMinimumWidth(48)
        else:
            b.setIconSize(QSize(18, 18))
            b.setFixedHeight(22)
            if text:
                b.setText(label)
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.clicked.connect(lambda _=False, c=cmd: self.run(c))
        return b

    def big(self, cmd, label, ic=None):
        b = self._btn(cmd, label, ic, big=True)
        self.row.addWidget(b)
        return b

    def col(self, items, text=True):
        """一欄最多三個小按鈕。items: (指令, 標籤[, 圖示名])"""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        for it in items:
            v.addWidget(self._btn(it[0], it[1], it[2] if len(it) > 2 else None, text=text))
        v.addStretch()
        self.row.addWidget(w)

    def widgets(self, ws):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 0, 2, 0)
        v.setSpacing(1)
        for x in ws:
            v.addWidget(x)
        v.addStretch()
        self.row.addWidget(w)


class Ribbon(QTabWidget):
    def __init__(self, run):
        super().__init__()
        self.setObjectName("ribbon")
        self.run = run
        self.setFixedHeight(120)
        # Important on Linux/X11/Wayland: the ribbon contains many fixed-width
        # controls.  If Qt is allowed to propagate their combined sizeHint to the
        # top-level window, the main window acquires a huge effective minimum width
        # and cannot be resized smaller.  Ignore the horizontal size hint; each tab
        # gets its own horizontal scroller below.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def page(self, title):
        # Put the wide ribbon contents inside a horizontal QScrollArea.  This is
        # mostly invisible on a wide screen, but on smaller Linux desktops it
        # prevents the ribbon from dictating the minimum width of QMainWindow.
        content = QWidget()
        content.setMinimumWidth(0)
        h = QHBoxLayout(content)
        h.setContentsMargins(3, 2, 3, 2)
        h.setSpacing(3)
        h.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        h.addStretch()

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        scroll.setMinimumWidth(0)
        scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.addTab(scroll, title)
        return h

    def panel(self, page, title):
        p = Panel(title, self.run)
        page.insertWidget(page.count() - 1, p)
        return p


class PropCombo(QComboBox):
    """功能區上的圖層／顏色／線型／線粗下拉清單。"""

    def __init__(self, width=150):
        super().__init__()
        self.setFixedWidth(width)
        self.setFixedHeight(22)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.keys = []

    def fill(self, entries, current):
        """entries: [(key, 顯示文字, icon 或 None)]；current 不在清單內時顯示為空白。"""
        self.blockSignals(True)
        self.clear()
        self.keys = [e[0] for e in entries]
        for key, text, ic in entries:
            if ic is not None:
                self.addItem(ic, text)
            else:
                self.addItem(text)
        self.setCurrentIndex(self.keys.index(current) if current in self.keys else -1)
        self.blockSignals(False)

    def key(self, i):
        return self.keys[i] if 0 <= i < len(self.keys) else None


COLOR_KEYS = [BYLAYER, BYBLOCK, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def color_entries(extra=None):
    out = []
    for c in COLOR_KEYS + ([extra] if extra is not None and extra not in COLOR_KEYS else []):
        out.append((c, color_name(c), swatch(aci_rgb(c)) if 0 < c < 256 else swatch((120, 128, 138))))
    out.append(("pick", "選取顏色...", None))
    return out


def lw_entries():
    return [(v, lw_name(v), None) for v in [LW_BYLAYER, LW_DEFAULT] + LINEWEIGHTS]


# ---------------------------------------------------------------- 指令行
class CmdEdit(QLineEdit):
    submit = Signal()
    escape = Signal()

    def __init__(self):
        super().__init__()
        self.text_mode = False
        self.hist = []
        self.hpos = 0

    def remember(self, s):
        if s.strip() and (not self.hist or self.hist[-1] != s):
            self.hist.append(s)
            del self.hist[:-100]
        self.hpos = len(self.hist)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.clear()
            self.escape.emit()
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or (k == Qt.Key.Key_Space and not self.text_mode):
            self.submit.emit()
            return
        if k in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.hist:
            self.hpos = max(0, min(len(self.hist), self.hpos + (-1 if k == Qt.Key.Key_Up else 1)))
            self.setText(self.hist[self.hpos] if self.hpos < len(self.hist) else "")
            return
        super().keyPressEvent(e)


class CommandLine(QFrame):
    submitted = Signal(str)
    cancelled = Signal()
    keyword = Signal(str)

    def __init__(self, names):
        super().__init__()
        self.setObjectName("cmdFrame")
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 2, 4, 3)
        v.setSpacing(2)
        self.log = QPlainTextEdit()
        self.log.setObjectName("cmdLog")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(64)
        self.log.setMaximumBlockCount(2000)
        self.log.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        v.addWidget(self.log)
        row = QHBoxLayout()
        row.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(icon("CMD").pixmap(18, 18))
        row.addWidget(ic)
        self.prompt = QLabel()
        self.prompt.setObjectName("cmdPrompt")
        self.prompt.setTextFormat(Qt.TextFormat.RichText)
        self.prompt.linkActivated.connect(self.keyword.emit)
        row.addWidget(self.prompt)
        self.edit = CmdEdit()
        self.edit.setObjectName("cmdEdit")
        self.edit.setPlaceholderText("鍵入指令")
        self.edit.submit.connect(self._submit)
        self.edit.escape.connect(self.cancelled.emit)
        row.addWidget(self.edit, 1)
        v.addLayout(row)
        self.completer = QCompleter(sorted(names))
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.edit.setCompleter(self.completer)

    def _submit(self):
        s = self.edit.text()
        self.edit.clear()
        if self.completer.popup().isVisible():
            self.completer.popup().hide()
        self.edit.remember(s)
        self.submitted.emit(s)

    def append(self, text):
        self.log.appendPlainText(text)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_prompt(self, html_text, text_mode=False):
        self.prompt.setText(html_text)
        self.prompt.setVisible(bool(html_text))
        self.edit.text_mode = text_mode
        idle = not html_text
        self.edit.setPlaceholderText("鍵入指令" if idle else "")
        self.edit.setCompleter(self.completer if idle else None)

    def type_text(self, t):
        self.edit.setFocus()
        self.edit.insert(t)


def status_button(ic, tip, checked=None):
    b = QToolButton()
    b.setAutoRaise(True)
    b.setIcon(icon(ic))
    b.setIconSize(QSize(18, 18))
    b.setFixedSize(28, 24)
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if checked is not None:
        b.setCheckable(True)
        b.setChecked(checked)
    return b
