# PyCAD 2D v0.5.1 改善內容

- TRIM / EXTEND：選取目標物件時按住 Shift，可暫時互換修剪與延伸。
- ARRAY：改為關聯式 Array 圖元，保留來源幾何與矩形/環形參數。
- ARRAYEDIT / ARE：可修改關聯式陣列參數；EXPLODE 可分解為一般圖元。
- HATCH：新增 ANSI32~38、BRICK、AR-CONC、AR-HBONE、AR-PARQ1、GRAVEL、HEX、STEEL 等常用畫面樣式。
- F11：新增物件鎖點追蹤 OTRACK。
- Shift+右鍵：新增單次暫時物件鎖點選單，可選端點、中點、中心、交點、垂直、切點、最近點等，亦可暫時關閉下一次鎖點。
- UNITS / UN：新增圖面單位對話框與顯示精度，可讀寫 DXF $INSUNITS。
- Pylance：為 app.run() / main.py argv 補上型別註記，改善 run partially unknown 警告。

注意：完整 GUI 自動測試需要 PySide6。此次環境未安裝 PySide6，因此已完成全專案 compileall 與純資料模型/關聯式陣列序列化測試；GUI 行為仍建議在 Windows 實機啟動後再做一次操作驗證。
