# PyCAD2D v0.5.2

- 修正狀態列 **物件鎖點追蹤 OTRACK (F11)** 圖示空白。
- 原因：v0.5.1 狀態列已引用 `OTRACK`，但 `icons.py` 的向量圖示表沒有 `OTRACK` 定義。
- 新增 OTRACK 專用向量圖示，開啟/關閉 F11 時圖示會正常顯示並保留原有 checked 高亮效果。
