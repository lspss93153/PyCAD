#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="0.6.9.4"
PKGROOT="${TMPDIR:-/tmp}/pycad_deb_build_$$"
OUT="${ROOT}/dist/PyCAD_v${VERSION}_Linux_Mint_Ubuntu_GPLv3.deb"
rm -rf "${PKGROOT}"
trap 'rm -rf "${PKGROOT}"' EXIT
mkdir -p "${PKGROOT}/DEBIAN" "${PKGROOT}/opt/pycad" "${PKGROOT}/usr/bin" \
  "${PKGROOT}/usr/share/applications" "${PKGROOT}/usr/share/doc/pycad" "${ROOT}/dist"
chmod 0755 "${PKGROOT}/DEBIAN"

# Copy source, excluding repository/build artifacts.
tar -C "${ROOT}" \
  --exclude='.git' --exclude='.github' --exclude='build' --exclude='dist' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='*.deb' --exclude='*.zip' --exclude='*.tar.gz' \
  -cf - . | tar -C "${PKGROOT}/opt/pycad" -xf -

cp "${ROOT}/LICENSE" "${PKGROOT}/usr/share/doc/pycad/copyright"
cp "${ROOT}/THIRD_PARTY_NOTICES.md" "${PKGROOT}/usr/share/doc/pycad/THIRD_PARTY_NOTICES.md"

cat > "${PKGROOT}/DEBIAN/control" <<CONTROL
Package: pycad
Version: ${VERSION}
Section: graphics
Priority: optional
Architecture: all
Maintainer: PyCAD Project
Depends: python3 (>= 3.10), python3-venv, python3-pip, libxcb-cursor0
Recommends: libgl1, libegl1
Description: PyCAD open-source 2D/3D CAD application
 GPLv3-licensed Python/PySide6 CAD application with 2D drafting,
 3D modeling and Linux/X11/Wayland compatibility improvements.
CONTROL

cat > "${PKGROOT}/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
APP=/opt/pycad
if [ ! -d "$APP/.venv" ]; then
  python3 -m venv "$APP/.venv"
fi
"$APP/.venv/bin/python" -m pip install --upgrade pip
"$APP/.venv/bin/python" -m pip install -r "$APP/requirements.txt"
"$APP/.venv/bin/python" -m pip install -r "$APP/requirements_3d.txt" || \
  echo "Optional 3D dependencies failed to install; core PyCAD remains available."
exit 0
POSTINST
chmod 0755 "${PKGROOT}/DEBIAN/postinst"

cat > "${PKGROOT}/usr/bin/pycad" <<'LAUNCHER'
#!/bin/sh
exec /opt/pycad/.venv/bin/python /opt/pycad/main.py "$@"
LAUNCHER
chmod 0755 "${PKGROOT}/usr/bin/pycad"

cat > "${PKGROOT}/usr/share/applications/pycad.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=PyCAD
Comment=Open-source 2D/3D CAD application
Exec=pycad %F
Terminal=false
Categories=Graphics;Engineering;
MimeType=application/dxf;
DESKTOP

dpkg-deb --root-owner-group --build "${PKGROOT}" "${OUT}"
echo "Built: ${OUT}"
