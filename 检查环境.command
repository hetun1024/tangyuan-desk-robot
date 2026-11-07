#!/bin/bash
# 双击这个，一条条告诉你哪里好了、哪里没装。
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "找不到 python3"; read -n 1 -s -r -p "按任意键关闭"; exit 1; }
"$PY" tools/selfcheck.py
echo ""
read -n 1 -s -r -p "  按任意键关闭窗口"
