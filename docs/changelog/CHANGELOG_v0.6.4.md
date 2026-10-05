# PyCAD v0.6.4 — Correctness & CAD Core

## 2D 修正
- 關聯式矩形陣列的 row/column spacing 改成本地向量；ROTATE/SCALE/MIRROR 正確跟隨。
- Polar Array 鏡射反轉 fill direction。
- ARRAY 增加 10,000 項互動安全限制、100,000 硬限制與展開快取。
- ARRAY grips 實作基本移動/間距編輯。
- HATCH 使用 ezdxf canonical PAT definitions（可用時），支援 dash/dot sequence；命令選項不再漏列已定義樣式。
- 封閉直線 Polyline OFFSET 加入 Shapely buffer cleanup；過大 inward offset 不建立反轉輪廓。
- JOIN 共線、相接 LINE 回傳單一 LINE。
- DXF/DWG 匯出不再誤清除 native document modified flag。

## 3D 正確性
- 修正 isometric projection basis；XYZ 軸等長投影，sphere orthographic silhouette 不再被拉成橢圓。
- camera_forward/depth 改依目前視圖，修正 Top/Front/Right 等 shaded ordering。
- Shaded Solid3D 改為跨物件 global face ordering。
- 等角/非 Top grid 改成 WCS 平面投影；非 Top window selection 改用 projected screen geometry。
- 修正從標準視圖開始 Orbit 的角度跳動。
- SWEEP Polyline path crash 修正。
- Polyline bulge arcs 在 EXTRUDE/REVOLVE/LOFT/SWEEP 的 exact path/profile 中保留。
- Concave EXTRUDE 優先走 OpenCascade B-Rep。
- Solid3D 新增 exact BREP payload；STEP 匯出優先使用 exact shape。
- BOX/CYLINDER/CONE/SPHERE/TORUS 建立 exact B-Rep（CadQuery 可用時）。
- SLICE X/Y/Z 使用正確半空間 box，排除 zero-volume phantom result。
- FILLETEDGE/CHAMFEREDGE 可選單一 edge 或 All。
- x,y,z / @x,y,z 文字輸入支援；多個 primitive 支援非零 Z 起點。
- MOVE3D 使用 base/second point；ROTATE3D/SCALE3D 可指定 base point。
- STL normals 修復、import vertex merge；VRML multi-shape import 修復。
- 3D Solid 的 Properties / LIST 新增尺寸、體積、vertex/face count、BREP 狀態。
- DXF/DWG 遇 3D solid 會先警告，不再靜默遺失。

## 效能
- Associative Array parts cache。
- Solid tessellation display edges 只保留 boundary/crease feature edges，避免 fillet 後把每個 triangle diagonal 都當可見 edge。
- Solid pick 對超密 edge set 做候選降採樣。

## 測試 / 版本
- 新增 tests/test_regressions_v064.py。
- test_io 改為 pytest parameterize；沒有 PySide6 時 render/UI tests skip。
- 版本統一為 0.6.4，修正舊 CHANGELOG_v0.5.1 標題。

## 已知尚未完成
- DXF 原生 associative array round-trip。
- Associative HATCH boundary、arc-edge native boundary。
- MLEADER/TABLE/IMAGE/REGION、polyline width/truecolor/rich MText 等完整 DXF 語意保真。
- side view 的完整工作平面/UCS 滑鼠繪圖。
- 真正 hidden-line removal / z-buffer。
- PRESSPULL face detection、Dynamic UCS、drag Gizmo、interactive quad viewport。
- 完整 Surface/Mesh/Materials/Lights/Render/ACIS SAT。
