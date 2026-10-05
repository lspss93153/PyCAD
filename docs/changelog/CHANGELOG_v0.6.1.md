# PyCAD v0.6.1

## 3D workspace / UI
- Drafting & Annotation now hides the 3D Model ribbon completely.
- 3D Model ribbon appears only in the 3D workspace.
- Added AutoCAD-style navigation grouping, visual-style controls and 3D export commands.
- Added a compact clickable ViewCube.

## Navigation
- Fixed mouse-wheel zoom in non-TOP views by preserving projected coordinates under the cursor.
- Added free 3D orbit with Shift + middle mouse drag.
- Added one-shot 3DORBIT command mode.

## Display
- Added 3D Wireframe, Shaded with Edges and Conceptual visual styles.
- Added face rendering for Solid3D.

## 3D file export
- Added STL export.
- Added STEP export through CadQuery.
- Added OBJ export.
- Completed polygon faces for cylinder, sphere and extrusion solids so exports contain closed surfaces where possible.

## Compatibility
- Existing .pycad projects remain readable.
- STEP export requires CadQuery; STL and OBJ have no additional 3D dependency.
