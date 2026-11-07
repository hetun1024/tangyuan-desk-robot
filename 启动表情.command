#!/bin/bash
# 双击这个，就会开出一个会眨眼的窗口。
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "找不到 python3"; read -n 1 -s -r -p "按任意键关闭"; exit 1; }

"$PY" -c "import cv2" 2>/dev/null || {
  echo "第一次用，正在装 opencv（约 1 分钟）…"
  "$PY" -m pip install --user -i https://pypi.tuna.tsinghua.edu.cn/simple opencv-python
}

# 先把上次没关干净的关掉，不然端口会被占着
pkill -f "face\.py" 2>/dev/null
sleep 0.5

"$PY" face.py
CODE=$?
if [ $CODE -ne 0 ]; then
  echo ""
  echo "  ✗ 窗口没开起来（退出码 $CODE）。把上面几行发给我。"
  echo ""
  read -n 1 -s -r -p "  按任意键关闭窗口"
fi
