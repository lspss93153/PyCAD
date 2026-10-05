# Contributing to PyCAD

謝謝你願意改善 PyCAD。

## 基本流程

1. Fork repository，從目前主分支建立 feature/fix branch。
2. 修改前盡量先建立可重現案例或測試。
3. 執行 `python -m pytest -q`。
4. Pull Request 請說明：問題、修改內容、如何測試、是否影響 2D/3D/檔案格式。
5. 若修改 UI，建議附上 Linux/Windows 截圖或短影片。

## 授權

提交 Pull Request 即表示你有權提交該程式碼，並同意你的貢獻依本專案的 **GPL-3.0-only** 授權發布。

請不要直接複製無權重新授權的商業 CAD 原始碼、圖示、說明文件、字型、測試圖檔或其他受保護素材。

## 相容性與品牌

可以實作一般 CAD 慣例、公開檔案格式與互通功能，但 UI 文案、圖示與文件應維持 PyCAD 自己的設計。第三方產品名稱只在說明相容性或技術背景確有必要時使用。
