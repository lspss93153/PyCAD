# PyCAD v0.6.9.5 — 幾何可靠性修復與繁中／英文介面預覽版

**發布日期 / Release date:** 2026-10-19
**版本狀態 / Status:** Alpha / Pre-release
**授權 / License:** GPL-3.0-only

> **重要提醒：這是公開測試版，仍不建議將 PyCAD 當成唯一的生產環境 CAD 工具。** 在開啟、修改或匯出 STEP、DXF、STL 等工程檔案前，請保留原始檔並獨立確認尺寸、幾何與加工結果。
>
> **Important:** This is an alpha release. Keep backups and independently verify critical CAD geometry and manufacturing dimensions.

## 一、v0.6.9.5 更新重點 / What's new

### 已修復 / Fixes

1. **STEP／BREP 精確幾何維護（高優先級）**
   修復含精確曲面的 STEP 模型在部分 2D `MOVE`、`ROTATE`、等比例 `SCALE` 後遺失 BREP、導致重新匯出時退化成三角化平面曲面的問題。現在會對精確 BREP 一併執行 OpenCascade 變換；對無法安全保留精度的非等比例變形，採明確拒絕並提示，避免無聲資料劣化。

2. **圖塊 Undo／Redo 修復**
   修改 Undo 快照的圖塊資料複製方式，修正直接改動圖塊內部物件後，Undo 仍保留修改內容的情況。

3. **glTF／GLB 單位換算**
   依 glTF 的公尺單位規則，在匯入／匯出時與圖面單位（預設毫米）換算，避免 1 m 被當成 1 mm 的 1000 倍尺寸差異。

4. **顯示網格 LOD 保護**
   對原始封閉網格進行簡化後，若結果失去封閉性，改回使用原顯示網格，以降低顯示破洞、假缺角風險。此保護可能降低特定模型的顯示速度，並非全面的 GPU 加速。

5. **原生專案檔案寫入可靠性**
   加強寫入後同步及寫入失敗時 `.tmp` 暫存檔清理，維持原子替換的防護機制。

### 新增與調整 / Additions

- **繁體中文／English 切換（第一階段）**：新增「語言 / Language」切換，涵蓋主要選單、Ribbon、工作區與常用標籤，並記住使用者選擇。部分進階對話框、錯誤訊息和指令提示仍尚未翻譯。
- **Windows 雙擊安裝入口**：提供 `PyCAD_v0.6.9.5_Windows_Click_Install.zip`；解壓縮後執行 `Install_PyCAD_Windows.cmd`。這是安裝腳本，不是已封裝的原生 Setup EXE。
- **Linux Mint／Ubuntu `.deb`**：提供可透過套件管理器安裝的 `.deb`；首次啟動仍需連網下載 Python 依賴。
- **更新日誌集中管理**：版本紀錄統一存放於 `docs/changelog/`；附繁中／英文安裝說明 `docs/INSTALL_zh_TW_en.md`。
- **CI 發行工作流程**：加入 GitHub Actions 的 Windows NSIS EXE 和 Linux DEB 建置配方；**Windows EXE 尚未在實際 Windows 環境完成建置及驗證**。

## 二、下載項目與安裝提醒 / Assets & installation

| 資產 | 用途 | 必須注意 |
|---|---|---|
| `PyCAD_v0.6.9.5_Windows_Click_Install.zip` | Windows 11 雙擊安裝腳本與程式檔案 | 需解壓縮；需要網路和相容的 Python 3.12／winget；尚未完成 Windows 實機驗收 |
| `PyCAD_v0.6.9.5_Linux_Mint_Ubuntu_GPLv3_Installer.deb` | Linux Mint／Ubuntu 套件 | `.deb` 已建置、未在目標 GUI 環境安裝驗證；首次啟動需要網路 |
| `PyCAD_v0.6.9.5_GitHub_Public_GPLv3_Source.zip` | 完整 GPLv3 原始碼 | 安裝依賴與執行環境需要使用者準備 |
| `PyCAD_v0.6.9.5_SHA256SUMS.txt` | 三個發行資產的 SHA-256 校驗值 | 用於檢查下載完整性，不是數位簽章 |

Linux 安裝：`sudo apt install ./PyCAD_v0.6.9.5_Linux_Mint_Ubuntu_GPLv3_Installer.deb`
Windows 安裝：解壓縮 ZIP，雙擊 `Install_PyCAD_Windows.cmd`。

## 三、測試與驗證狀態 / Verification

- 2026-10-19 重新執行原始碼測試：**59 passed、5 skipped**。
- `compileall` 編譯檢查通過；Linux `.deb` 建置及套件中繼資料檢查通過。
- 追加 BREP 變換、非等比例變換拒絕、圖塊復原、glTF 單位往返、英文字典等回歸檢查。
- **5 項略過的測試與未完成的 GUI／平台驗收，代表無法宣稱程式所有功能或安裝檔都沒有 Bug。**

## 四、已知限制與特別說明 / Known limitations

1. **Alpha，不是正式穩定版。** 已修復的是已重現的特定問題，不能保證所有 Bug 均排除。
2. **Windows 沒有現成、已驗證的原生 `.exe` 安裝程式。** GitHub Actions 可以嘗試建置 NSIS EXE，建置成功後也仍需要 Windows 11 手動測試，才能作為正式發行資產。
3. **安裝不完全離線。** Windows 安裝腳本及 Linux 首次啟動可能需網路取得 Python、PySide6、CadQuery 及其他套件；某些 3D 依賴可能因平台而安裝失敗。
4. **英文翻譯尚未涵蓋所有介面。** 主要 UI 有切換功能，但深層對話框、命令列提示和部分錯誤訊息仍有繁體中文。
5. **大型 STEP／STL 與 3D 顯示仍有架構限制。** 現行 3D 以 CPU／QPainter 繪製，複雜遮擋排序、背景匯入、龐大 Assembly 效能等尚未徹底改善。
6. **其他格式相容性需要實際樣本測試。** 特別是 DWG／ODA、組件 STEP、特殊曲面與第三方輸出檔案。
7. **請勿直接覆蓋唯一一份工程檔。** 建議先複製一份進行測試，再比對尺寸及曲面資料。

## 五、未來持續開發方向 / Planned improvements

以下為**規劃方向，非已完成項目，版本內容與發布時間可能依實際測試調整**。

| 預計版本 | 開發目標 | 重點 |
|---|---|---|
| **v0.6.9.6** | 大型模型可靠性與安裝完善 | STEP／STL 背景匯入、進度顯示與取消、異常回報、記憶體與網格處理、Windows／Linux 實機安裝測試 |
| **v0.7.0** | 內部架構與原生檔案 | 模組重整、幾何操作統一、Undo／Redo 交易安全、`.pycad` 壓縮／版本控制、備份與復原 |
| **v0.8.0** | 新一代 3D Viewport | 使用具深度緩衝的 GPU 繪圖、改善遮擋、光影、模型選取及操作流暢度；保留整合式顯示晶片與 CPU 安全備援 |
| **v0.9.0** | 正式發行品質準備 | 更完整的繁中／英文覆蓋、可直接安裝的 Windows EXE 與 Linux 發行包、跨平台 CI／GUI 驗收、文件與新手導覽 |

### 長期目標

持續改善 2D／3D 製圖的操作效率、STEP／STL 相容性、CAD 精確幾何品質、大檔案效能、跨平台安裝及無障礙使用體驗，逐步將 PyCAD 打造成可供社群測試和貢獻的開源 CAD 工具。

---

## English summary

**PyCAD v0.6.9.5 is an alpha pre-release**, focusing on geometry correctness and first-stage Traditional Chinese/English UI switching. It fixes loss of exact STEP BREP data during selected 2D transformations, block Undo/Redo snapshots, and glTF/GLB meter-to-drawing-unit conversion. It adds a safer mesh-LOD fallback and improves atomic native-project writes. The release offers a Windows ZIP with a double-click installation script and a Linux `.deb` package. Both installation paths may require an internet connection, and neither is fully validated on the target desktop platforms. **There is no verified Windows native EXE installer yet.** Test results: **59 passed, 5 skipped**. The future roadmap includes background imports, project-format improvements, a GPU-backed 3D viewport with a CPU fallback, more complete English translations, and installer/platform validation. These are plans, not completed features.

**License:** GNU GPL v3.0 only. Full source and third-party notices are included in the repository.
