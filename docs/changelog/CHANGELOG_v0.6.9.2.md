# PyCAD v0.6.9.2 — Linux Viewport Zoom Compatibility

## Fixed

- Linux/Wayland/libinput smooth-scroll devices can report `pixelDelta()` without `angleDelta()`; viewport zoom now supports both event forms.
- Smooth touchpad scrolling uses proportional zoom instead of being ignored.
- 2D, 3D and four-view viewport zoom share the same cross-platform factor calculation.
- Large one-event scroll spikes are clamped to keep the model from jumping out of view.
- `main.py` imports are Ruff I001 compliant.

## Regression

- 51 passed, 5 skipped, 0 failed.
