# PyCAD v0.6.5.4 — 3D OSNAP / Transform Stability Hotfix

本版不新增任何指令、格式或建模功能，只完善 v0.6.5.x 已存在的 3D 操作與外部模型工作流。

## 3D 物件鎖點

- 修正 3D 點輸入路徑在取得 XYZ 工作平面座標後直接返回，導致 F3 OSNAP 在 `MOVE3D` / `ROTATE3D` / `SCALE3D` 完全失效的問題。
- 新增既有 OSNAP 模式的真正 XYZ 候選：
  - `END`：3D 實體真實頂點。
  - `MID`：3D 邊中點。
  - `CEN`：圓/橢圓邊中心與面中心，可直接取得 CYLINDER 上下圓面中心。
  - `GCE`：3D 實體包圍盒幾何中心。
  - `NEA`：沿 feature edge 取得真正 XYZ 最近點。
- BREP / STEP 優先讀 OpenCascade topology，不從 tessellation 猜圓心或面中心。
- STL / OBJ 等 Mesh 使用匯入時建立的 bounded feature-edge cache；鎖點候選有上限並快取，避免大型 Mesh 每次 mouse move 掃描全部三角形。
- 3D 鎖點判斷改為目前 viewport 的像素空間距離，因此在 SE Isometric、Front、Right 與四視埠中仍可正確吸附。
- 3D snap marker 改用 XYZ 投影繪製，不再錯誤呼叫 2D `w2s(x,y)`。

## 3D Gizmo / 選取顯示

- Gizmo 原點由「所有 tessellation 頂點平均值」改為選取實體的 3D bounding-box 中心，避免 STEP/STL 網格密度不均造成 Gizmo 偏移。
- 匯入 STEP/STL 在選取亮顯時使用較嚴格的 crease 閾值，保留輪廓與真正銳邊，同時減少平滑曲面上的短碎線。

## 外部模型驗證

實際使用使用者提供的模型做回歸：

- `Chess Rook.STEP`：1 solid，22,594 vertices / 45,184 faces；BREP snap cache 226 個候選，第一次建立約 0.034 s，之後 cache hit 約 0.005 ms。
- `desk_oganizer.stl`：1 mesh，72,702 vertices / 145,400 faces；bounded 3D snap cache 1,821 個候選，第一次建立約 0.011 s，之後 cache hit 約 0.053 ms。

## 測試

新增 `tests/test_regressions_v0654.py`，涵蓋 BOX 頂點/邊中點/面中心、精確 BREP CYLINDER 上下圓面中心與大型 Mesh snap cache 上限。

測試結果：**37 passed, 4 skipped, 0 failed**。Skipped 項目為目前 headless 建置環境缺少 PySide6 GUI runtime 的 GUI 測試。
