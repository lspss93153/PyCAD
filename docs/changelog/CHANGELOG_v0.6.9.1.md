# v0.6.9.1 — TAB Gizmo Exact Entry Fix

- Fixed Qt focus traversal consuming TAB before Canvas received it.
- Click-only X/Y/Z gizmo selection now stays armed after mouse release.
- Exact workflow: click Z → TAB → type -20 → Enter.
- Numeric text is buffered inside the gizmo interaction itself; command-line focus is no longer required.
- Mouse movement after an armed click does not move the solid until a real drag begins.
- Esc cancels and restores the original geometry; Enter commits one undo record.
