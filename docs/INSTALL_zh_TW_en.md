# PyCAD v0.6.9.5 安裝說明 / Installation Guide

## Linux Mint / Ubuntu
1. 下載 `PyCAD_v0.6.9.5_Linux_Mint_Ubuntu_GPLv3_Installer.deb`。
2. 雙擊 `.deb`，使用系統套件安裝器安裝；或在終端機執行 `sudo apt install ./PyCAD_v0.6.9.5_Linux_Mint_Ubuntu_GPLv3_Installer.deb`。
3. 在應用程式選單啟動 **PyCAD**。首次啟動需要網路下載 Python 套件至 `~/.local/share/pycad/venv`，錯誤日誌：`~/.local/share/pycad/install.log`。3D 套件可能安裝失敗，屆時僅 2D 功能較可靠。
4. 移除：`sudo apt remove pycad`，不會自動清除個人繪圖與使用者設定。

English: double-click the `.deb`, then launch PyCAD from the application menu. First launch requires an internet connection to install per-user Python dependencies. The initial `.deb` installation is not a self-contained offline distribution.

## Windows 11
1. 解壓縮 `PyCAD_v0.6.9.5_Windows_Click_Install.zip`（不能直接在壓縮檔內執行）。
2. 雙擊 `Install_PyCAD_Windows.cmd`。安裝程式會使用 Python 3.12，如果找不到，嘗試透過 `winget` 安裝；第一次需要網路。
3. 安裝至 `%LOCALAPPDATA%\Programs\PyCAD`，在桌面與開始選單建立捷徑。
4. 移除：雙擊同資料夾內 `Uninstall_PyCAD_Windows.cmd`。這是安裝腳本，不是原生 EXE 安裝器；如果 PySide6、CadQuery 等模組不支援系統配置，安裝可能失敗。

English: extract the Windows ZIP first, then double-click `Install_PyCAD_Windows.cmd`. An internet connection is required. Uses Python 3.12; if missing, attempts winget installation. Desktop and Start Menu shortcuts are created.

## English / 繁體中文
在主程式選單 **語言 / Language** 切換 `English` 或 `繁體中文`。程式記住上次選擇。主要功能區已支援，但部分舊版子視窗與指令提示尚未完全翻譯。

## Build native Windows .exe installer on GitHub
Use **Actions → build installers → Run workflow** in your GitHub source repository. A Windows runner executes PyInstaller then NSIS and uploads the `.exe` as a workflow artifact. This build recipe has not been executed or runtime-tested in the current environment. Do not redistribute it as a verified binary until Windows smoke tests pass.

## Quality warning / 工程檔案警告
Alpha software. Back up all STEP, DXF and native project files before editing; verify manufacturing dimensions independently.
