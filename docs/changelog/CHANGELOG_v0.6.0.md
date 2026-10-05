# PyCAD v0.6.0 — 3D Foundation / View Update

- 新增 AutoCAD 風格標準視圖：Top、Front、Right、SE/SW/NE/NW Isometric。
- **東南等角視圖（SE Isometric）** 已加入「檢視」Ribbon 與檢視選單。
- View 引擎改為可投影 XYZ；舊 2D 圖元仍維持 Z=0，相容原有 .pycad。
- UCS 圖示升級為 X/Y/Z 三軸，會隨視圖方向改變。
- 新增工作區切換：製圖與註解 / 3D 基礎。
- 新增 AutoCAD 風格「3D 模型」Ribbon 頁面。
- 新增真正保存 XYZ 的 3DSOLID 輕量資料型別。
- 新增 BOX、CYLINDER、CONE、SPHERE 與 EXTRUDE（圓、封閉聚合線）第一階段建模。
- 3D 物件會保存於 .pycad，不會退化成 2D 複本。

## 尚未宣稱完成的 AutoCAD 3D 功能

v0.6.0 是 3D 核心第一階段。Boolean solids、3D gizmo、自由 Orbit、UCS 編輯、材質/光源、視覺樣式與 ACIS/SAT/DWG 3D 實體相容仍需後續版本實作。
