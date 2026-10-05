# PyCAD v0.6.9.3

- Fix Linux main-window resizing: ribbon tabs no longer impose a huge effective minimum width.
- Ribbon pages now scroll horizontally when the window is narrower than their contents.
- Initial window size is clamped to the current screen's available desktop geometry.
- Explicit main-window minimum size is 640x480 instead of inheriting the ribbon's aggregate size hint.
- Keeps the v0.6.9.2 Linux wheel/pixelDelta zoom fix.
