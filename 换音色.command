#!/bin/bash
# 双击这个文件，就能一个个听音色，选中哪个就用哪个。
cd "$(dirname "$0")" || exit 1
clear
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "  找不到 python3。先跑：xcode-select --install"
  read -n 1 -s -r -p "  按任意键关闭"
  exit 1
fi
"$PY" tools/voice_picker.py
echo ""
read -n 1 -s -r -p "  按任意键关闭窗口"
