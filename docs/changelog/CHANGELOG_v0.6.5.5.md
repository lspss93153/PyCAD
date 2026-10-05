# PyCAD v0.6.5.5 — 3D WorkPlane / Correctness Stability Hotfix

## 核心修正
- 建立單一 WorkPlane 核心，統一 3D mouse / typed coordinate / direct distance。
- WCS 固定 world XY；工作平面 normal 朝相機但不改變 WCS U/V 軸語意。
- ray-plane 平行時回傳 None，拒絕 advance command，顯示明確提示。
- 3D ORTHO / Polar / Snap / OTRACK 改在 local UV 運算。
- Dynamic UCS 在取點前更新可見面，使用 NumPy 加速投影、edge distance、triangle hit。
- depth-aware entity picking；Wireframe 不允許 face-interior hit。
- Solid3D grips 暫停回傳假 XY bbox grips。
- find_boundary() 排除 Solid3D，避免 HATCH / PRESSPULL 2D graph 污染。
- Gizmo Undo 延遲到第一次真正位移。
- 3D Orbit 在 mouse press 固定 pivot，旋轉後補償 ox/oy，降低畫面漂移。
- 移除 UI 不可達的 SHADED visual-style 分支入口，保留 2D Wireframe / 3D Wireframe / Shaded with Edges / Conceptual。

## 效能
- requirements_3d.txt 明確加入 NumPy。
- Dense triangular meshes 使用向量化 vertex projection / point-in-triangle / edge distance。

## 驗證
- compileall 通過。
- pytest：37 passed；GUI/可選依賴測試在目前環境共 5 skipped。
- 新增 tests/test_regressions_v0655.py，覆蓋 WCS/FRONT/BOTTOM/typed UCS 與 Solid3D grips。
