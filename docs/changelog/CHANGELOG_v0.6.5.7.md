# PyCAD v0.6.5.7 — 3D Placement & Boolean Precision

## 3D precision placement
- Added `PLACE3D` (`3P`) for source-reference to target-face placement.
- Target face acquisition works directly during the placement command; Dynamic UCS does not need to be enabled manually.
- After choosing the target point, numeric U/V offsets are applied in the target face and N is applied along the face outward normal. Negative N therefore moves into a normal outward-facing solid face, which is useful for positioning drilling/cutting tools.
- Dynamic input shows the current target-face local U/V/N readout while picking the face.
- Placement preserves exact BREP data when CadQuery/OpenCascade is available.

## Boolean precision
- `SUBTRACT` now has explicit two-stage semantics: select Base solids, Enter, then select Tool solids, Enter.
- Selection order no longer silently decides which solid subtracts which.
- A volumetric-intersection preflight rejects no-overlap/contact-only cases instead of producing a misleading result.
- Tool solids are consumed only after a successful volumetric cut.
- `INTERSECT` reports a clear message for empty volumetric intersections.

## Workflow target
Typical drilling workflow: select cylinder -> snap its bottom centre -> click the box target face -> enter U/V fine offsets -> enter negative N depth -> `SUBTRACT` Base then Tool.
