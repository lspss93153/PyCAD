# PyCAD v0.6.5.2 — External 3D Import / Viewer Stability Hotfix

本版不新增任何指令或檔案格式，只改善既有 3D 匯入與顯示的正確性、穩定性與效能。

## 修正

- STEP/STP 顯示三角化改成依模型尺寸自動調整，不再固定使用 `0.35` 公差。
- STEP 保留精確 OpenCascade BREP；畫面網格只作顯示快取，複雜模型會建立有上限的 LOD。
- STL/OBJ/PLY/OFF/3MF/glTF/GLB/DAE 匯入增加網格清理：剔除 NaN/Inf、無效索引、退化面與重複三角形。
- STL/一般 Mesh 會合併重複頂點並嘗試修正多實體法向方向。
- glTF/GLB/3MF/DAE 等 Scene 匯入會套用節點 transform，避免零件全部疊在原點造成「破圖」。
- 3D Renderer 使用暫存顯示 LOD；原始 STL 網格與 STEP BREP 不因此被破壞。
- Shaded/Conceptual 增加安全面數預算、退化面防護、非有限座標防護與封閉網格背面剔除，降低 painter-order 破面。
- Wireframe/選取亮顯改走受限顯示網格，避免幾十萬條三角邊在每次滑鼠移動時重畫。
- 匯入期間暫停 Canvas repaint 並使用等待游標，完成後一次更新，避免半完成狀態觸發重繪。
- 匯入完成後指令列顯示物件／頂點／面數，方便判斷模型複雜度。

## 資料保真

- STEP：BREP 仍為權威幾何；LOD 只影響畫面。
- STL/OBJ 等 Mesh：完整清理後的原始 Mesh 仍保留於圖元；LOD 只存在記憶體快取，不寫入 `.pycad`。

## Regression tests

新增測試覆蓋：

- 壞頂點／退化面清理
- 大型 Mesh 顯示 LOD 上限
- STL 重複頂點合併
- STEP BREP 保存與顯示面數上限
