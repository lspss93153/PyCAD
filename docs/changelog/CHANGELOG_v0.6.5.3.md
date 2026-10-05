# PyCAD v0.6.5.3 — Imported 3D Visual Fidelity / Stability Hotfix

本版不新增指令或檔案格式，只改善 v0.6.5.2 已有的 3D 匯入與顯示路徑。

## 修正

- STL / STEP 匯入後不再預設以 3D Wireframe 顯示全部三角化邊；改用既有「著色含邊線」。
- 2D Wireframe 對 3D 網格只顯示邊界、銳邊與依目前視角計算的 silhouette，不再把 coplanar triangle diagonal 當成 CAD 邊。
- Shaded with Edges / Conceptual 的邊線改成 feature/silhouette edges，避免平滑曲面變成白色亂線團。
- 修正 v0.6.5.2 position-only vertex-cluster LOD 可能把薄壁模型內外兩側合併，導致跨面長線、尖刺與破面。
- LOD 現在優先使用 topology-preserving quadric simplification（若環境有 backend），否則使用 normal-aware clustering，分離相反/急遽不同法向的表面。
- Orbit / Gizmo 拖曳時使用較低顯示面數預算；放開後自動重建完整品質 cache，降低大型 STL/STEP 在互動中閃退的機率。
- Renderer 增加極端投影座標保護，避免損壞模型或異常相機狀態將過大座標送進 QPainter。
- 匯入 mesh 的 picking/edit edge cache 優先保存真正邊界與銳邊，而不是任意三角網格對角線。

## 回歸測試

- 新增薄壁雙層 mesh LOD 測試，確認內外表面不會被 weld 成單一平面。
- 新增 coplanar triangles feature-edge 測試，確認內部三角對角線不會出現在乾淨線架構中。
- 完整測試：34 passed, 4 skipped, 0 failed。

## 說明

STL 本質上仍是三角網格；切換到「3D 線架構」時仍會看到網格線，這是該視覺型式的預期行為。一般檢視建議使用「著色含邊線」或「概念」。
