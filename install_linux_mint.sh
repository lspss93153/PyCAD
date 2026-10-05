#!/usr/bin/env bash
set -e
sudo apt update
sudo apt install -y python3 python3-venv python3-pip libxcb-cursor0
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
if ! .venv/bin/pip install -r requirements_3d.txt; then
  echo "CadQuery 安裝失敗：PyCAD 仍可使用，STL/OBJ/PLY/OFF 仍可使用；STEP/布林需要 CadQuery，3MF/glTF 需要 trimesh。"
fi
echo
echo "PyCAD v0.6.9.4 安裝完成"
echo "執行： ./run.sh"
