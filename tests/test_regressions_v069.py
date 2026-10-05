# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path


def test_gizmo_numeric_workflow_is_wired_into_canvas_and_commandline():
    root=Path(__file__).resolve().parents[1]
    canvas=(root/'pycad2d'/'canvas.py').read_text(encoding='utf-8')
    app=(root/'pycad2d'/'app.py').read_text(encoding='utf-8')
    assert 'def begin_gizmo_numeric' in canvas
    assert 'def accept_gizmo_numeric' in canvas
    assert 'axis=gd.get("constraint")' in canvas
    assert 'tr=tuple(av[i]*v for i in range(3))' in canvas
    assert 'if self._gizmo_drag is not None:' in canvas
    assert 'if self.begin_gizmo_numeric():return' in canvas
    assert 'if cv.gizmo_numeric_active():' in app
    assert 'cv.accept_gizmo_numeric(text)' in app


def test_gizmo_preview_does_not_push_undo_until_commit():
    root=Path(__file__).resolve().parents[1]
    canvas=(root/'pycad2d'/'canvas.py').read_text(encoding='utf-8')
    preview=canvas.split('def _gizmo_preview_translation',1)[1].split('def _gizmo_restore_originals',1)[0]
    commit=canvas.split('def _finish_gizmo_translation',1)[1].split('def gizmo_numeric_active',1)[0]
    assert 'push_undo' not in preview
    assert 'self.doc.push_undo()' in commit

def test_gizmo_tab_intercepts_qt_focus_traversal():
    from pathlib import Path
    canvas = Path(__file__).parents[1].joinpath('pycad2d','canvas.py').read_text(encoding='utf-8')
    block=canvas.split('def focusNextPrevChild',1)[1].split('def keyPressEvent',1)[0]
    assert 'self.begin_gizmo_numeric()' in block


def test_gizmo_numeric_has_local_buffer_and_armed_click():
    from pathlib import Path
    canvas = Path(__file__).parents[1].joinpath('pycad2d','canvas.py').read_text(encoding='utf-8')
    assert 'numeric_buffer' in canvas
    assert 'click Z → TAB → -20 → Enter' in canvas
    assert 'gd["armed"]=True' in canvas
    assert 'if not gd.get("mouse_down",False)' in canvas
