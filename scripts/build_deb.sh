#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="0.6.9.5"
PKGROOT="$(mktemp -d)"
OUT="${ROOT}/dist/PyCAD_v${VERSION}_Linux_Mint_Ubuntu_GPLv3_Installer.deb"
trap 'rm -rf "${PKGROOT}"' EXIT
mkdir -p "${PKGROOT}/DEBIAN" "${PKGROOT}/opt/pycad" "${PKGROOT}/usr/bin" \
  "${PKGROOT}/usr/share/applications" "${PKGROOT}/usr/share/doc/pycad" "${ROOT}/dist"
# No downloaded Python packages in the source package. GUI + 3D dependencies are
# installed in each user's venv on first start, never as root inside dpkg postinst.
tar -C "$ROOT" --exclude='./.git' --exclude='./.github' --exclude='./build' \
  --exclude='./dist' --exclude='./.pytest_cache' --exclude='./.coverage' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='*.deb' --exclude='*.zip' \
  --exclude='./tests' -cf - . | tar -C "$PKGROOT/opt/pycad" -xf -
cp "$ROOT/LICENSE" "$PKGROOT/usr/share/doc/pycad/copyright"
cp "$ROOT/THIRD_PARTY_NOTICES.md" "$PKGROOT/usr/share/doc/pycad/THIRD_PARTY_NOTICES.md"
cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: pycad
Version: ${VERSION}
Section: graphics
Priority: optional
Architecture: all
Maintainer: PyCAD Project
Depends: python3 (>= 3.10), python3-venv, python3-pip, libxcb-cursor0, libgl1, libegl1
Recommends: libxkbcommon-x11-0, libxcb-xinerama0
Description: PyCAD 2D/3D CAD application (GPL-3.0-only)
 Desktop 2D/3D CAD with STEP, DXF and mesh workflows.
 First startup needs internet to prepare per-user Python dependencies.
EOF
cat > "$PKGROOT/usr/bin/pycad" <<'LAUNCHER'
#!/bin/sh
set -eu
APP=/opt/pycad
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/pycad"
ENV="$DATA/venv"
STAMP="$DATA/.ready_0.6.9.5"
LOG="$DATA/install.log"
mkdir -p "$DATA"
error_message() {
  echo "PyCAD setup failed. See $LOG" >&2
  if command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    zenity --error --title='PyCAD' --text="PyCAD setup failed. See $LOG" 2>/dev/null || true
  fi
}
if [ ! -f "$STAMP" ]; then
  echo "PyCAD first launch: installing GUI dependencies for your user (internet required)..." >&2
  if command -v notify-send >/dev/null 2>&1; then
    notify-send 'PyCAD v0.6.9.5' 'First launch: preparing Python dependencies (internet required).' 2>/dev/null || true
  fi
  if ! (python3 -m venv "$ENV" && "$ENV/bin/python" -m pip install -r "$APP/requirements.txt" &&
        "$ENV/bin/python" -c 'import PySide6, ezdxf, shapely, numpy') >"$LOG" 2>&1; then
    error_message; exit 1
  fi
  # 3D extras are optional. Keep the functioning 2D application if optional wheel
  # availability differs across Linux distributions / Python versions.
  if ! "$ENV/bin/python" -m pip install -r "$APP/requirements_3d.txt" >>"$LOG" 2>&1; then
    echo 'PyCAD: optional 3D dependency setup incomplete; details in install.log' >&2
  fi
  touch "$STAMP"
fi
exec "$ENV/bin/python" "$APP/main.py" "$@"
LAUNCHER
chmod 0755 "$PKGROOT/usr/bin/pycad"
cat > "$PKGROOT/usr/share/applications/pycad.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=PyCAD
Name[zh_TW]=PyCAD 製圖軟體
Comment=Open-source 2D/3D CAD application
Comment[zh_TW]=開源 2D／3D 電腦輔助設計軟體
Exec=pycad %F
Icon=applications-graphics
Terminal=false
StartupNotify=true
Categories=Graphics;Engineering;
DESKTOP
chmod 0644 "$PKGROOT/usr/share/applications/pycad.desktop"
chmod 0755 "$PKGROOT/DEBIAN"
dpkg-deb --root-owner-group --build "$PKGROOT" "$OUT"
echo "Built: $OUT"
