# PyCAD v0.6.5.6 — 2D/3D Precision Interaction

這一版不擴張指令數量，集中改善「畫得準、移得準、不要跑偏」的日常操作手感。

## 2D 精準繪圖
- Polar 預設由 90° 調整為 45°，一般機械/工程草圖更容易直接取得常用斜線。
- LINE / PLINE 等第二點輸入期間支援 `TAB` 快速循環角度增量：30° → 45° → 60° → 90° → 15°。
- `Shift+TAB` 反向循環；切換時自動開啟 Polar 並關閉 ORTHO，避免兩種約束互搶。
- 動態輸入提示會直接顯示目前 TAB 快速角度。
- Polar 右鍵選單與 Drafting Settings 新增 60° 增量。
- 既有精確輸入仍保留：`@dx,dy`、`@distance<angle`、直接距離。

## 3D SolidWorks-style Manipulator 改善
- X/Y/Z 箭頭改為真正的單軸 hard lock；拖 X 時 Y/Z 不會因滑鼠偏移而改變。
- 軸拖曳不再用單純 screen projection 換算距離，改為固定輔助平面 + mouse ray + axis parameter，降低等角視圖跑偏與跳動。
- 新增 XY / XZ / YZ 平面拖曳 handle；拖曳期間第三軸 bit-for-bit 鎖為 0 位移。
- Gizmo 實際 hit tolerance 放大，視覺仍維持細線，較容易抓取箭頭。
- 拖曳 HUD 顯示軸距離或 ΔX/ΔY/ΔZ，使用者可立即確認目前 constraint。
- 修正混合選取時 gizmo preview 對錯實體的 mapping 風險。
- BREP 仍只在 mouse release 時做一次精確 transform，拖曳 preview 使用輕量 mesh clone。

## WorkPlane / DUCS 穩定性
- 多點 3D 操作取得第一個 reference 後鎖定 WorkPlane。
- Dynamic UCS 只負責決定操作開始的平面；拖曳/第二點期間不會因游標滑過其他面偷偷換平面。
- 操作完成或取消後自動解除 plane lock。

## 驗收方向
- Z 軸 gizmo 移動：ΔX = 0、ΔY = 0 必須完全成立。
- XZ plane handle：ΔY = 0 必須完全成立。
- 2D LINE：TAB 可快速取得 30/45/60/90/15° Polar 增量。
