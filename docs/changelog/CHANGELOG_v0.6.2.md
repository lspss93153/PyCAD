# PyCAD v0.6.2

## 3D 建模
- 新增 WEDGE、PYRAMID、TORUS。
- 新增 MOVE3D、ROTATE3D、SCALE3D。
- 新增 UNION、SUBTRACT、INTERSECT（CadQuery/OpenCascade）。
- 保留 BOX、CYLINDER、CONE、SPHERE、EXTRUDE/PRESSPULL。

## AutoCAD 風格工作區
- 工作區改為「製圖與註解 / 3D 建模」。
- 2D 工作區不顯示 3D 模型 Ribbon。
- 3D Ribbon 分為實體、布林、3D 修改、視圖/導覽、視覺型式與 3D 資料交換。
- 保留 SE/SW/NE/NW 等角視圖、3D Orbit、ViewCube、游標中心縮放。

## 3D 檔案
### 可匯入
STEP/STP、STL、OBJ、PLY、OFF、3MF、glTF/GLB。

### 可匯出
STEP/STP、STL、OBJ、PLY、OFF、3MF、glTF/GLB。

STEP 與布林需要 CadQuery；3MF/glTF/GLB 與部分 STL 匯入能力使用 trimesh。
