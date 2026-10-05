# SPDX-License-Identifier: GPL-3.0-only
"""以程式繪製的向量圖示（24x24 格座標）。全部是自行設計的簡單圖形。"""
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QBrush, QPolygonF, QFont, QPainterPath

COL = {"w": "#dfe5ea", "b": "#4da3ff", "o": "#ffb347", "g": "#62d26f", "r": "#ff6b6b", "d": "#8894a3", "y": "#ffe066"}

_LAYERS = "p 12 4 21 9 12 14 3 9 12 4;p 3 13 12 18 21 13;p 3 17 12 22 21 17"
_SHEET = "p 12 5 21 10 12 15 3 10 12 5"
_MAG = "c 10 10 6;w 2.2;l 14.5 14.5 21 21;w 1.5;k b"

ICONS = {
    "LINE": "l 4 20 20 4;n 4 20;n 20 4",
    "PLINE": "p 3 19 9 7 15 15 21 5;n 3 19;n 9 7;n 15 15;n 21 5",
    "CIRCLE": "c 12 12 8.5;n 12 12",
    "ARC": "a 12 17 10 20 140;n 2.6 13.6;n 21.4 13.6;n 12 7",
    "RECTANG": "r 4 6 16 12;n 4 6;n 20 18",
    "POLYGON": "p 12 3 20.5 9 17.3 19.5 6.7 19.5 3.5 9 12 3",
    "ELLIPSE": "e 12 12 9.5 5.5;n 12 12",
    "SPLINE": "s 3 17 8 1 15 23 21 7;n 3 17;n 21 7",
    "HATCH": "k b;l 4 12 12 4;l 4 20 20 4;l 12 20 20 12;l 4 16 16 4;l 8 20 20 8;k w;r 4 4 16 16",
    "XLINE": "k d;l 1 19 23 5;k w;l 5 16.5 19 7.5;n 12 12",
    "RAY": "l 4 18 22 6;n 4 18",
    "POINT": "k d;c 12 12 6;k b;f 12 12 2.2",
    "REVCLOUD": "a 7 9 4 20 200;a 14 7 4 -10 200;a 18 13 4 -80 200;a 14 18 4 170 200;a 7 16 4 110 200",
    "TEXT": "t 4 20 21 A",
    "MTEXT": "t 2 18 17 A;k b;l 14 7 21 7;l 14 11 21 11;l 14 15 21 15;l 3 21 21 21",
    "MOVE": "l 12 3 12 21;l 3 12 21 12;p 9 6 12 3 15 6;p 9 18 12 21 15 18;p 6 9 3 12 6 15;p 18 9 21 12 18 15",
    "COPY": "c 9 9 6;k b;c 15 15 6",
    "ROTATE": "a 12 12 8 40 270;g 20 4 21 11 15 8.5;k b;f 12 12 1.8",
    "SCALE": "r 4 12 8 8;k b;r 4 4 16 16;k o;l 13 11 19 5;p 15 5 19 5 19 9",
    "MIRROR": "p 3 6 9 12 3 18 3 6;k d;da;l 12 2 12 22;so;k b;p 21 6 15 12 21 18 21 6",
    "OFFSET": "a 4 20 15 0 90;k b;a 4 20 9 0 90",
    "TRIM": "l 3 12 9 12;l 16 12 21 12;k d;da;l 9 12 16 12;so;k b;l 9 4 9 20;l 16 4 16 20",
    "EXTEND": "l 3 12 12 12;k o;da;l 12 12 19 12;so;p 16 9 19 12 16 15;k b;l 20 4 20 20",
    "FILLET": "p 4 3 4 12;k b;a 12 12 8 180 90;k w;p 12 20 21 20",
    "CHAMFER": "p 4 3 4 12;k b;l 4 12 12 20;k w;p 12 20 21 20",
    "STRETCH": "r 3 8 11 8;k d;da;r 10 5 11 14;so;k o;l 15 12 22 12;p 19 9 22 12 19 15",
    "ARRAY": "r 3 3 5 5;r 10 3 5 5;r 17 3 5 5;r 3 10 5 5;r 17 10 5 5;r 3 17 5 5;r 10 17 5 5;r 17 17 5 5;k b;r 10 10 5 5",
    "ERASE": "k r;p 4 15 13 6 19 12 10 21 4 15;l 8.5 10.5 14.5 16.5;k d;l 3 22 21 22",
    "EXPLODE": "r 8 8 8 8;k o;l 6 6 3 3;l 18 6 21 3;l 6 18 3 21;l 18 18 21 21",
    "JOIN": "l 3 17 10 12.5;l 14 11.5 21 7;k b;c 12 12 2.6",
    "BREAK": "l 3 12 9 12;l 15 12 21 12;k r;l 10 7 12 17;l 12 7 14 17",
    "MATCHPROP": "r 5 3 9 6;l 9.5 9 9.5 13;k b;p 6 13 13 13 14 21 5 21 6 13",
    "DIVIDE": "l 3 12 21 12;k b;f 9 12 1.8;f 15 12 1.8;n 3 12;n 21 12",
    "OVERKILL": "l 4 8 20 8;k d;l 4 12 20 12;k r;l 8 14 16 20;l 16 14 8 20",
    "DIM": "l 4 5 4 20;l 20 5 20 20;k b;l 4 9 20 9;g 4 9 8.5 7.3 8.5 10.7;g 20 9 15.5 7.3 15.5 10.7;k o;t 8 20 9 12",
    "DIMLINEAR": "l 4 5 4 20;l 20 5 20 20;k b;l 4 10 20 10;g 4 10 8.5 8.3 8.5 11.7;g 20 10 15.5 8.3 15.5 11.7",
    "DIMALIGNED": "l 3 16 15 4;k b;l 7 20 19 8;l 3 16 8 21;l 15 4 20 9",
    "DIMRADIUS": "c 11 13 8;k b;l 11 13 16.7 7.3;g 16.7 7.3 12.5 8.6 15.3 11.5;f 11 13 1.5",
    "DIMDIAMETER": "c 12 12 8;k b;l 6.3 17.7 17.7 6.3;g 17.7 6.3 13.5 7.7 16.3 10.5;g 6.3 17.7 10.5 16.3 7.7 13.5",
    "DIMANGULAR": "l 4 20 21 20;l 4 20 16 5;k b;a 4 20 11 0 51",
    "MLEADER": "l 4 20 11 9;l 11 9 14 9;g 4 20 4.8 14.8 8.6 17.4;k b;l 16 7 22 7;l 16 11 22 11",
    "LAYER": _LAYERS,
    "LAYMCUR": _SHEET + ";k g;w 2.4;p 12 18 15 21 21 14",
    "LAYISO": _SHEET + ";k d;p 3 14 12 19 21 14;p 3 18 12 23 21 18",
    "LAYUNISO": _LAYERS + ";k g;f 19 5 2.5",
    "LAYOFF": "k d;c 12 10 6;l 9 19 15 19;l 10 22 14 22",
    "LAYON": "k y;c 12 10 6;k w;l 9 19 15 19;l 10 22 14 22",
    "LAYFRZ": "k b;l 12 3 12 21;l 4.2 7.5 19.8 16.5;l 4.2 16.5 19.8 7.5",
    "LAYTHW": "k y;c 12 12 4;l 12 2 12 5;l 12 19 12 22;l 2 12 5 12;l 19 12 22 12;l 5 5 7 7;l 17 17 19 19;l 5 19 7 17;l 17 7 19 5",
    "LAYLCK": "r 6 11 12 9;a 12 11 4 0 180",
    "LAYULK": "r 6 11 12 9;a 16 11 4 0 180",
    "BLOCK": "r 4 9 10 10;k b;c 15 9 5",
    "INSERT": "r 9 9 11 11;k o;l 3 3 9 9;p 5 9 9 9 9 5",
    "DIST": "r 3 9 18 7;l 7 9 7 12;l 11 9 11 13;l 15 9 15 12;l 19 9 19 13",
    "AREA": "k b;l 6 12 12 6;l 6 18 18 6;l 12 18 18 12;k w;r 5 5 14 14",
    "ID": "l 12 3 12 21;l 3 12 21 12;k b;c 12 12 3.5",
    "LIST": "r 5 3 14 18;k b;l 8 8 16 8;l 8 12 16 12;l 8 16 16 16",
    "PASTECLIP": "r 5 5 14 16;r 9 3 6 4;k b;l 8 12 16 12;l 8 16 16 16",
    "COPYCLIP": "r 4 4 11 13;k b;r 9 8 11 13",
    "CUTCLIP": "l 6 4 16 17;l 18 4 8 17;k b;c 7 19.5 2.5;c 17 19.5 2.5",
    "ZOOMEXT": _MAG + ";l 7 10 13 10;l 10 7 10 13",
    "ZOOMWIN": _MAG + ";r 7 8 6 4",
    "ZOOMPREV": _MAG + ";p 12 7 8 10 12 13",
    "VIEWTOP": "k b;p 5 6 19 6 19 18 5 18 5 6;k w;t 8 15 7 T",
    "VIEWFRONT": "k b;r 5 6 14 12;k w;t 8 15 7 F",
    "VIEWRIGHT": "k b;p 7 5 18 8 18 19 7 16 7 5;k w;t 9 15 7 R",
    "VIEWSEISO": "k b;p 12 3 21 8 12 13 3 8 12 3;p 3 8 12 13 12 22 3 17 3 8;p 12 13 21 8 21 17 12 22 12 13;k o;l 17 18 22 22;g 22 22 18 21 20 18",
    "VIEWSWISO": "k b;p 12 3 21 8 12 13 3 8 12 3;p 3 8 12 13 12 22 3 17 3 8;p 12 13 21 8 21 17 12 22 12 13;k o;l 7 18 2 22;g 2 22 6 21 4 18",
    "VIEWNEISO": "k b;p 12 3 21 8 12 13 3 8 12 3;p 3 8 12 13 12 22 3 17 3 8;p 12 13 21 8 21 17 12 22 12 13;k g;l 17 6 22 2",
    "VIEWNWISO": "k b;p 12 3 21 8 12 13 3 8 12 3;p 3 8 12 13 12 22 3 17 3 8;p 12 13 21 8 21 17 12 22 12 13;k g;l 7 6 2 2",
    "BOX": "p 4 8 12 4 20 8 12 12 4 8;p 4 8 4 17 12 21 12 12;p 12 12 20 8 20 17 12 21",
    "CYLINDER": "e 12 6 7 3;l 5 6 5 18;l 19 6 19 18;e 12 18 7 3",
    "CONE": "e 12 18 8 3;l 4 18 12 4;l 20 18 12 4",
    "SPHERE": "c 12 12 9;e 12 12 4 9;e 12 12 9 4",
    "EXTRUDE": "r 4 12 8 8;k b;p 12 12 18 6 22 10 16 16 12 12;l 12 20 16 16;l 12 12 12 20",
    "REGEN": "a 12 12 8 40 280;g 20 5 20.5 11.5 15 9",
    "PROPERTIES": "r 4 3 16 18;l 4 8 20 8;l 10 8 10 21;k b;l 12 12 18 12;l 12 16 18 16",
    "NEW": "p 6 3 15 3 19 7 19 21 6 21 6 3;p 15 3 15 7 19 7",
    "OPEN": "k o;p 3 19 3 6 9 6 11 8 20 8 20 19 3 19",
    "SAVE": "p 4 4 17 4 20 7 20 20 4 20 4 4;r 8 4 7 5;k b;r 7 13 10 7",
    "SAVEAS": "p 4 4 17 4 20 7 20 12;p 12 20 4 20 4 4;r 8 4 7 5;k o;l 13 21 21 13;l 13 21 12.5 18.5",
    "PLOT": "r 4 10 16 8;r 7 4 10 6;k b;r 7 15 10 6",
    "UNDO": "a 13 14 7 -10 190;g 3.5 9 10 8 7 14.5",
    "REDO": "a 11 14 7 0 190;g 20.5 9 14 8 17 14.5",
    "EXPORT": "r 4 9 12 12;k b;l 10 14 21 3;p 15 3 21 3 21 9",
    "PDF": "r 4 3 16 18;k r;t 5.5 16 8 PDF",
    "DXF": "r 4 3 16 18;k b;t 5.5 16 8 DXF",
    "SVG": "r 4 3 16 18;k g;t 5.5 16 8 SVG",
    "PNG": "r 4 3 16 18;k o;t 5.5 16 8 PNG",
    "DSETTINGS": "r 4 4 16 16;k g;r 9 9 6 6;n 4 4;n 20 20",
    "PURGE": "p 6 7 7 21 17 21 18 7;l 4 7 20 7;l 9 4 15 4;k b;l 10 10 10 18;l 14 10 14 18",
    "HELP": "c 12 12 9;k b;t 8.5 17 13 ?",
    "GRID": "l 3 8 21 8;l 3 16 21 16;l 8 3 8 21;l 16 3 16 21",
    "SNAP": "f 6 6 1.4;f 12 6 1.4;f 18 6 1.4;f 6 12 1.4;f 18 12 1.4;f 6 18 1.4;f 12 18 1.4;f 18 18 1.4;k b;f 12 12 2.2",
    "ORTHO": "w 2;p 5 4 5 19 20 19",
    "POLAR": "l 4 20 21 20;l 4 20 17 6;k b;a 4 20 10 0 47",
    "OSNAP": "r 6 6 12 12;k g;n 6 6;n 18 18;n 18 6;n 6 18",
    # Object Snap Tracking (F11): crosshair + acquired snap point + tracking rays.
    # v0.5.1 referenced OTRACK from the status bar but had no matching icon,
    # so Qt displayed an empty checked button.
    "OTRACK": "k d;da;l 4 12 20 12;l 12 4 12 20;so;k g;f 12 12 2.2;k b;l 12 12 20 4;l 12 12 20 20;n 12 12",
    "LWT": "w 1;l 4 6 20 6;w 2.2;l 4 12 20 12;w 3.6;l 4 18 20 18",
    "DYN": "l 9 2 9 16;l 2 9 16 9;k b;r 12 13 10 7",
    "CMD": "p 4 7 9 12 4 17;k b;l 11 17 20 17",
}


def _paint(p, spec):
    color = QColor(COL["w"])
    width = 1.5
    dashed = False

    def pen():
        pn = QPen(color, width)
        pn.setCapStyle(Qt.PenCapStyle.RoundCap)
        pn.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if dashed:
            pn.setStyle(Qt.PenStyle.DashLine)
        return pn

    for op in spec.split(";"):
        t = op.split()
        if not t:
            continue
        k = t[0]
        if k == "t":
            x, y, size, text = float(t[1]), float(t[2]), float(t[3]), " ".join(t[4:])
            f = QFont("DejaVu Sans")
            f.setPixelSize(int(size))
            f.setBold(True)
            path = QPainterPath()
            path.addText(QPointF(x, y), f, text)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawPath(path)
            p.setBrush(Qt.BrushStyle.NoBrush)
            continue
        a = [float(x) for x in t[1:]] if k not in ("k",) else t[1:]
        p.setPen(pen())
        p.setBrush(Qt.BrushStyle.NoBrush)
        if k == "k":
            color = QColor(COL.get(a[0], a[0]))
        elif k == "w":
            width = a[0]
        elif k == "da":
            dashed = True
        elif k == "so":
            dashed = False
        elif k == "l":
            p.drawLine(QPointF(a[0], a[1]), QPointF(a[2], a[3]))
        elif k == "c":
            p.drawEllipse(QPointF(a[0], a[1]), a[2], a[2])
        elif k == "e":
            p.drawEllipse(QPointF(a[0], a[1]), a[2], a[3])
        elif k == "a":
            p.drawArc(QRectF(a[0] - a[2], a[1] - a[2], 2 * a[2], 2 * a[2]), int(a[3] * 16), int(a[4] * 16))
        elif k == "r":
            p.drawRect(QRectF(a[0], a[1], a[2], a[3]))
        elif k == "p":
            p.drawPolyline(QPolygonF([QPointF(a[i], a[i + 1]) for i in range(0, len(a), 2)]))
        elif k == "g":
            p.setBrush(QBrush(color))
            p.drawPolygon(QPolygonF([QPointF(a[i], a[i + 1]) for i in range(0, len(a), 2)]))
        elif k == "s":
            path = QPainterPath(QPointF(a[0], a[1]))
            path.cubicTo(QPointF(a[2], a[3]), QPointF(a[4], a[5]), QPointF(a[6], a[7]))
            p.drawPath(path)
        elif k == "f":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(a[0], a[1]), a[2], a[2])
        elif k == "n":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(COL["b"])))
            p.drawRect(QRectF(a[0] - 1.8, a[1] - 1.8, 3.6, 3.6))


_cache = {}


def icon(name, size=64):
    key = (name, size)
    if key in _cache:
        return _cache[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    spec = ICONS.get(name)
    if spec:
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(size / 24.0, size / 24.0)
        _paint(p, spec)
        p.end()
    ic = QIcon(pm)
    _cache[key] = ic
    return ic


def swatch(rgb, size=14, border="#9aa5b1"):
    """顏色方塊圖示。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setPen(QPen(QColor(border), 1))
    p.setBrush(QBrush(QColor(*rgb)))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pm)
