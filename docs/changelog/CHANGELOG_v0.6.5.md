# PyCAD v0.6.5 — Existing Feature Completion & Stability

本版**不新增指令或工作區功能**。目標是把 v0.6.4 已經存在的 2D / 3D 功能補正、減少資料遺失，並把檔案讀寫與互動行為做穩。

## 檔案讀寫 / I/O

- 合併使用者提供的新 `io_utils.py` 的 ODA File Converter 啟動修正：隔離 PyCAD 的 Qt plugin / platform 環境變數、Windows 隱藏轉檔視窗、5 分鐘 timeout、轉檔錯誤碼檢查與小寫 wildcard。
- 保留 v0.6.4 已有的 BREP、STEP、STL 法向、STL 合併頂點、VRML 多物件修正，避免直接覆蓋新 IO 時反而退回舊行為。
- AutoCAD 2010 DXF round-trip 現在保留 Entity TrueColor (group 420)。
- LWPOLYLINE 保留 constant width 與各頂點 start/end width。
- HATCH 匯入 / 匯出可保存 line / arc 邊界，不再把圓弧邊界一律折成多邊形。
- STEP 匯入即使有單位換算，也盡量先縮放 exact OpenCascade shape 再保存 BREP，而不是只保留顯示網格。
- 直接「匯出 DXF」和「另存 DXF/DWG」都會在圖面含 3D Solid 時明確警告，不再讓使用者誤以為 3D 已保存。

## 2D 校正

- Array 延續 v0.6.4 的旋轉 / 比例 / 鏡射正確性，並改善矩形 / 環形 Array grips 的幾何方向與參數修改。
- 大型 Array hit-test 改為參數化鄰近項目檢查，避免 hover / pick 每次展開全部成員。
- HATCH 增加內部穩定 entity identity；使用「選取物件」建立的 Hatch 會保存邊界關聯，MOVE / ROTATE / SCALE 等一對一編輯後可重新生成邊界。
- `.pycad` 專案保存邊界 entity uid 與 Hatch association，舊 v5 專案仍可讀。
- HATCH 精確 arc boundary 可直接顯示並 round-trip 到 R2010 DXF。
- DXF TrueColor、Polyline width 已加入 model / renderer / import / export 的完整路徑。
- 保留 v0.6.4 已完成的 Array transform、Array 安全上限/快取、標準 PAT、過大 inward OFFSET 防護、凹形 OFFSET 清理、共線 LINE JOIN。

## 3D 校正

- SWEEP fallback 現在沿 Polyline 的實際 primitive 路徑取樣，bulge arc 不再退化成直線 chord。
- WEDGE / PYRAMID 使用 exact planar BREP（CadQuery/OpenCascade 可用時），STEP 不再只能由 display mesh 重建。
- MOVE / ROTATE / SCALE / MIRROR（2D 指令套用 Solid3D）與 MOVE3D / ROTATE3D / SCALE3D / MIRROR3D 盡量維持 exact BREP。
- STEP import 單位縮放後仍盡量保存 exact BREP。
- 3D 顯示網格採 adaptive tessellation；複雜 fillet / boolean 不再固定產生過密的互動 mesh。
- FRONT / BACK / LEFT / RIGHT 的點輸入使用 XZ / YZ 工作平面；VIEW UCS 具真正 view-plane inverse mapping。
- UCS grid 會跟著 TOP / FRONT / RIGHT / VIEW 工作平面顯示，避免 UCS 只改左下角文字。
- F6 Dynamic UCS 在 planar face hover 時可將點投影到該 face plane。
- 四視埠已有 active viewport cursor / selection / point preview 路徑，不再把所有點擊送到被覆蓋的單一主視圖。
- 3D Move Gizmo 的 X/Y/Z 軸可拖曳，並在完成時保留 exact BREP。
- PRESSPULL 已是封閉區域按拉，不再只是 EXTRUDE 的別名。
- 3D DXF/DWG 資料遺失會先警告；STL orientation、VRML multi-shape、STL vertex merge 延續 v0.6.4 修正。

## 測試

- 新增 `tests/test_regressions_v065.py`，覆蓋：大型 Array picking、Array grips、TrueColor / Polyline width DXF round-trip、HATCH arc boundary round-trip、ODA Qt 環境隔離、exact wedge BREP、STL vertex merge、associative Hatch 與 `.pycad` 關聯保存。
- 此建置環境最終測試：`24 passed, 3 skipped`。3 個 skip 為缺少 PySide6 的 GUI 自動測試；所有 Python 檔案另通過 `compileall`。

## 範圍說明

v0.6.5 沒有加入 v0.6.4 原本不存在的新指令（例如新的 2D command 或新的 Surface/Mesh/Render 系統）。本版只處理已存在功能的正確性、I/O 保真、穩定性與互動一致性。
