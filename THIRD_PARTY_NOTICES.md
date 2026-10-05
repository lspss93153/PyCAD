# Third-Party Notices

PyCAD 自有程式碼採 **GPL-3.0-only**。PyCAD 會在執行或安裝時使用下列第三方套件；這些套件仍由各自權利人依各自授權條款提供，**不因 PyCAD 採 GPL 而改變其原始授權**。

目前 repository 的安裝腳本透過 `pip` 取得套件，並未把下列第三方專案的完整原始碼直接 vendoring 到 PyCAD repository。

| 元件 | 用途 | 上游授權（摘要） |
|---|---|---|
| PySide6 / Qt for Python | GUI / Qt | LGPL-3.0 / GPL-3.0 / 商業授權（依 Qt 發行條款與模組而定） |
| ezdxf | DXF 匯入/匯出 | MIT |
| Shapely | 2D 幾何 / offset cleanup | BSD-3-Clause |
| NumPy | 數值運算 | 主要為 BSD-3-Clause；發行 wheel 可能另含其隨附元件授權 |
| CadQuery | STEP / OpenCascade 幾何工作流 | Apache-2.0 |
| OCP (CadQuery dependency) | OpenCascade Python binding | Apache-2.0 |
| trimesh | Mesh I/O / processing | MIT |
| NetworkX | trimesh 部分功能 | BSD-3-Clause |
| pycollada | COLLADA/DAE | BSD-style license |

## 重要說明

1. **實際安裝版本為準。** Python wheel/conda package 可能另外包含下游或 vendored 元件；散布完整二進位 bundle 時，請保留該發行包隨附的 license/notice 檔。
2. PyCAD 的 Linux `.deb` 公開版不直接內嵌上述 Python 套件，而是在安裝後建立虛擬環境並由 `pip` 下載，所以 `.deb` 主要散布的是 PyCAD 自有 GPL 原始碼與啟動檔。
3. ODA File Converter 為可選外部程式，不由 PyCAD repository 散布。使用者需自行依 ODA 的授權條款取得與安裝。
4. 如果未來把 Qt/PySide6、OpenCascade、GEOS、NumPy wheels 或其他第三方二進位直接封裝進 AppImage、Flatpak、Windows EXE 或離線 `.deb`，發布者應再次檢查並隨附那些實際二進位所要求的完整 license notices/source offer/relinking obligations。

## Upstream

- Qt for Python: https://doc.qt.io/qtforpython-6/
- ezdxf: https://github.com/mozman/ezdxf
- Shapely: https://github.com/shapely/shapely
- NumPy: https://numpy.org/
- CadQuery: https://github.com/CadQuery/cadquery
- OCP: https://github.com/CadQuery/OCP
- trimesh: https://github.com/mikedh/trimesh
- NetworkX: https://github.com/networkx/networkx
- pycollada: https://github.com/pycollada/pycollada

This file is an attribution/compliance aid, not legal advice. When distributing a binary bundle, verify the exact dependency versions and the license files shipped with those exact builds.
