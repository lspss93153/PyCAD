# PyCAD v0.6.9.5 — 幾何可靠性與雙語安裝測試版
Release notes / 發行日期：2026-10-19

## 已修復 / Fixed

- **STEP / BREP 精度**：在 2D MOVE、ROTATE、等比例 SCALE 時，將 OpenCascade 變換同步套用至精確 BREP，而非刪除 BREP 退化成三角化 STEP。若為不支援的非等比例變形，明確取消操作並提示錯誤。保留舊版 `.pycad` 幾何讀取方式。
- **圖塊 Undo / Redo**：Undo 快照對圖塊採深層複製，修復直接修改圖塊內容後 Undo 無法恢復的問題。
- **glTF / GLB 單位**：依 glTF 規範處理公尺；在檔案匯入與匯出時換算至工程圖面 INSUNITS (預設毫米)。
- **封閉網格 LOD**：當簡化結果讓原本封閉的網格不再 watertight，改用原始顯示網格，避免顯示假缺口；代價是此類模型可能較慢。此項不等於 GPU 重寫或全面效能提升。
- **原生檔案寫入**：寫入完成後 fsync，若失敗清除 `.tmp` 暫存檔，維持原子替換。
- **英文介面（第一階段）**：新增 English／繁體中文選單，主要選單、Ribbon、工作區及常用標籤切換，QSettings 保留偏好。保留 CAD 指令代碼，不翻譯圖檔資料；部分較深層對話框與指令提示仍為繁體中文。
- **安裝與發行**：Linux Mint / Ubuntu `.deb`、Windows 雙擊安裝腳本與 Windows EXE 的 GitHub Actions / NSIS 建置配方；Windows EXE 未在本環境建置。集中歷史日誌至 `docs/changelog/`。

## 測試 / Verification

- Linux / Python 3.13：`python -m compileall` 通過；`pytest` 57 passed, 5 skipped (PySide6 GUI unavailable)。
- 追加 6 個新測試：BREP 變換、非等比拒絕、圖塊復原、glTF 往返、英文字典。
- `dpkg-deb --build` / `dpkg-deb --info` 通過，但未在 Mint/Ubuntu 目標機安裝驗證。

## 已知限制 / Known limitations

- `.deb` 能雙擊安裝，但首次啟動會在使用者目錄建立 Python venv，**需要網路**下載依賴；不是離線完整 AppImage。
- Windows ZIP 的雙擊 CMD/PowerShell 安裝腳本需要網路，並依賴 Python 3.12／winget；尚未在實際 Windows 11 測試。
- GitHub Actions 可以產生 NSIS Windows EXE，但此處無 Windows 編譯器與圖形測試環境，**沒有已驗證的 EXE 可供直接下載**。
- GUI 大量測試需 Windows 11／Linux Mint 實機驗證；部分功能對話框、錯誤文字以及 CAD 指令提示尚未全面翻譯。
- 3D QPainter 渲染、背景匯入、大型 CAD Assembly 效能、DWG ODA 相容性等仍需後續版本處理；不能宣稱所有程式 Bug 已清零。
