# PyCAD v0.6.9.1 — Precision Gizmo & Workflow Polish

## 3D Gizmo exact numeric movement

- X/Y/Z axis drag now supports **TAB → exact distance → Enter**.
- Example: grab the Z triad, press TAB, type `-20`, Enter → exact `ΔX=0, ΔY=0, ΔZ=-20`.
- Typed distance is measured from the entity's position at the start of the gizmo operation, not added on top of the mouse preview.
- Mouse release while numeric entry is active keeps the axis constraint alive until Enter/Esc.
- Esc restores the pre-drag geometry exactly.
- Gizmo preview is now undo-free; a successful commit creates exactly one undo record.
- Exact commit rebuilds/preserves translated BREP where available.

## Existing v0.6.8 practical baseline retained

- WorkPlane-aware 3D primitives and practical PLACE3D attach/direction/mm workflow.
- Multi-LOD mesh cache + cached NumPy hit buffers for large STL/STEP interaction.
- HATCH island area correction, editable DXF DIMENSION import, recursive ARRAY guard.
- SUBTRACT Base/Tool workflow, safe REVOLVE rejection, display/export mesh separation.
- Dynamic Input TAB still switches Distance/Angle when no 3D Gizmo axis drag is active.

## Validation

- `python -m compileall`: passed.
- `pytest`: 47 passed / 5 skipped in the build environment (PySide6 GUI tests skipped).
