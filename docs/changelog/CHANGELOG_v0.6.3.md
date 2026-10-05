# PyCAD v0.6.3

## 3D 建模
- 新增 REVOLVE、SWEEP、LOFT。
- 新增 FILLETEDGE、CHAMFEREDGE、MIRROR3D、SLICE。
- 保留 BOX/CYLINDER/CONE/SPHERE/WEDGE/PYRAMID/TORUS、EXTRUDE/PRESSPULL 與 UNION/SUBTRACT/INTERSECT。

## AutoCAD 風格 3D 工作區
- 3D 模式新增「實體 / 曲面 / 網面 / 視覺化」Ribbon 頁籤。
- 製圖與註解模式會隱藏所有 3D 專用頁籤。
- 新增四視埠 VPORTS/4V（Top / Front / Right / SE Isometric）。
- 新增選取 3D 實體時的 XYZ Gizmo 顯示。
- 新增 UCS 基本模式，以及 F6 動態 UCS 狀態。
- 延續 ViewCube、3D Orbit、視覺型式、游標中心滾輪縮放。

## 3D 檔案交換
- 原有：STEP/STP、STL、OBJ、PLY、OFF、3MF、glTF/GLB。
- 新增：AMF 讀寫、VRML/WRL 讀寫、Collada DAE 讀寫。
- DAE 需 trimesh + pycollada；STEP 與實體邊圓角/倒角需 CadQuery/OpenCascade。

## 修正
- 修正 v0.6.2 3D 匯入後使用不存在的 set_view_preset API。
- 3D 工作區版本文字更新為 v0.6.3。
