#!/bin/bash
cd "$(dirname "$0")" || exit 1
clear
PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "找不到 python3"; read -n 1 -s -r -p "按任意键关闭"; exit 1; }
"$PY" tools/sound_check.py
echo ""
read -n 1 -s -r -p "  按任意键关闭窗口"
