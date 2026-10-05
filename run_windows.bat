@echo off
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
  echo Installing optional 3D STEP/Boolean/mesh support...
  .venv\Scripts\pip install -r requirements_3d.txt || echo 3D optional packages install failed - basic STL/OBJ/PLY/OFF still work; STEP/Boolean/3MF/glTF/DAE may be unavailable.
)
.venv\Scripts\python main.py %*
