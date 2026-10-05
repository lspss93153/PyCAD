# PyCAD v0.6.8 — Practical 2D/3D Precision & Stability

- WorkPlane-aware BOX/WEDGE/CYLINDER/CONE/PYRAMID/TORUS/SPHERE mesh + BREP.
- First-point geometric plane lock with separate UCS coordinate origin.
- Practical PLACE3D: attach target → direction → millimetres; advanced U/V/N retained.
- Multi-LOD display mesh cache and cached NumPy hit buffers; projected AABB candidate filtering.
- Opaque face lighting, reduced triangle seams, no hidden-back crease lines.
- 3D TOP depth-aware picking, previous-view azimuth/elevation restore, quad-view wheel zoom, real status Z.
- COPY/Paste Solid3D XYZ/BREP preservation; safe REVOLVE crossing-axis rejection; stable LOFT order.
- Hatch island area fix, editable DXF DIMENSION import, recursive nested-array cap.
- TAB restores distance/angle dynamic-input semantics.
- Exact BREP export tessellation separated from display LOD for STL/OBJ.
- Regression suite: 47 passed, 5 skipped (PySide6 unavailable in build environment).
