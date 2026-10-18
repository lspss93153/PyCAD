; SPDX-License-Identifier: GPL-3.0-only
; Build on WINDOWS with NSIS after python -m PyInstaller ... --onedir.
!include "MUI2.nsh"
!define VERSION "0.6.9.5"
Name "PyCAD ${VERSION}"
OutFile "dist\PyCAD_v${VERSION}_Windows_Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\PyCAD"
RequestExecutionLevel user
Unicode true
ShowInstDetails show
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "TradChinese"
Section "PyCAD" SEC01
  SetOutPath "$INSTDIR"
  File /r "dist\PyCAD\*.*"
  File "LICENSE"
  File "THIRD_PARTY_NOTICES.md"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\PyCAD"
  CreateShortCut "$SMPROGRAMS\PyCAD\PyCAD.lnk" "$INSTDIR\PyCAD.exe"
  CreateShortCut "$SMPROGRAMS\PyCAD\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\PyCAD.lnk" "$INSTDIR\PyCAD.exe"
SectionEnd
Section "Uninstall"
  Delete "$DESKTOP\PyCAD.lnk"
  Delete "$SMPROGRAMS\PyCAD\PyCAD.lnk"
  Delete "$SMPROGRAMS\PyCAD\Uninstall.lnk"
  RMDir "$SMPROGRAMS\PyCAD"
  RMDir /r "$INSTDIR"
SectionEnd
