@echo off
setlocal
set "HERE=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HERE%Install_PyCAD_Windows.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] PyCAD installation did not finish. Check the messages above.
  pause
  exit /b 1
)
echo.
echo [OK] PyCAD has been installed. You can open it from the Desktop or Start menu.
pause
