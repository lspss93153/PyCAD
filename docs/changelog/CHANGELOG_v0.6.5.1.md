# PyCAD v0.6.5.1 — 3D Stability Hotfix

本版不新增指令、不新增檔案格式、不新增工作區功能，只修正 v0.6.5 已存在功能的 3D 顯示、互動與穩定性。

## 修正

- 修正 3D 建模指令（例如 CYLINDER、SPHERE、MOVE3D 等）進入 XYZ 點輸入後滑鼠游標消失：
  - 3D command point 改以 `project3()` 投影，不再把 `(x, y, z)` 直接傳給只接受 `(x, y)` 的 `w2s()`。
  - 3D 工作區保留 Qt CrossCursor 作為安全游標；即使預覽繪製發生例外，也不會留下完全不可見的滑鼠。
  - Pan / Orbit / Gizmo 結束後依工作區正確恢復游標。
  - 3D 動態輸入顯示 XYZ 與 ΔX/ΔY/ΔZ，不再只套用 2D 距離顯示。
- 修正 SPHERE exact BREP 只生成半球：CadQuery `makeSphere()` 預設角度是 0°~90°，現在明確使用 -90°~+90° 建立完整球體。
- 基本 3D primitive 保留原生輕量顯示網格，只把 OpenCascade BREP 附加為精確幾何核心；避免球體等基本實體因 OCC 重三角化而顯示稀疏或不完整，並降低繪圖負擔。
- 改善 2D Wireframe / 3D Wireframe 的既有視覺型式差異：
  - 2D Wireframe 使用實體的語意／特徵邊。
  - 3D Wireframe 顯示面網格邊，提供更明確的空間曲面結構。
  - 複雜模型限制最多約 6000 條顯示邊，避免圓角／布林後滑鼠再次嚴重卡頓。
- 修正 FRONT / RIGHT / Isometric 等非 TOP 視圖對 Solid3D 使用 2D XY bbox 做 culling 的問題，避免 Z 範圍可見但整個 3D 物件被錯誤剔除。
- 3D 半徑點輸入在 XYZ 點存在時改用真正 3D 距離，避免側視圖只看 XY 而得到 0 或錯誤半徑。

## 文件整理

- 所有歷史 `CHANGELOG_*.md` 統一移到 `docs/changelog/`。
- 根目錄保留 `README.md` 作為安裝與使用入口；版本修改紀錄不再散落在根目錄。

## 測試

- 新增 `tests/test_regressions_v0651.py`。
- 驗證完整球體 mesh bbox、完整球體 BREP bbox/體積、3D cursor XYZ projection 防回歸，以及 2D/3D wireframe 分流。
- Headless 建置環境結果：`28 passed, 3 skipped`；skip 為需要 PySide6 GUI 的測試。
