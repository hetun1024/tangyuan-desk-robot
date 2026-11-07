#!/bin/bash
# 双击这个文件就能启动「大脑」。
# 第一次会先让你填 API key，之后选打字还是说话。

cd "$(dirname "$0")" || exit 1
clear

echo ""
echo "  =========================================="
echo "     汤圆 · TangYuan"
echo "  =========================================="
echo ""

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "  ✗ 找不到 python3。先装命令行工具：xcode-select --install"
  read -n 1 -s -r -p "  按任意键关闭窗口"
  exit 1
fi

# 依赖（第一次要装，之后秒过）
if ! "$PY" -c "import vosk, sounddevice, cv2, faster_whisper" >/dev/null 2>&1; then
  echo "  第一次运行，装几个组件（约 1—5 分钟，只装这一次）。"
  echo ""
  # 一个一个装：某一个失败不会把后面全带崩
  FAILED=""
  while IFS= read -r pkg; do
    [ -z "$pkg" ] && continue
    case "$pkg" in \#*) continue;; esac
    # 已经装过的跳过，别每次都重装一遍
    case "$pkg" in
      faster-whisper*) MOD=faster_whisper ;;
      edge-tts*)       MOD=edge_tts ;;
      opencv-python*)  MOD=cv2 ;;
      sounddevice*)    MOD=sounddevice ;;
      vosk*)           MOD=vosk ;;
      numpy*)          MOD=numpy ;;
      *)               MOD="" ;;
    esac
    if [ -n "$MOD" ] && "$PY" -c "import $MOD" >/dev/null 2>&1; then
      printf "   %-28s 已有 ✓\n" "$pkg"
      continue
    fi

    printf "   装 %-24s" "$pkg"
    # 先走清华源（国内快），失败再用默认源
    if "$PY" -m pip install --user --quiet --disable-pip-version-check \
         -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120 --retries 3 \
         "$pkg" >/tmp/puffer_pip.log 2>&1; then
      echo "✓"
    elif "$PY" -m pip install --user --quiet --disable-pip-version-check \
         --timeout 120 --retries 3 "$pkg" >>/tmp/puffer_pip.log 2>&1; then
      echo "✓（默认源）"
    else
      echo "✗"
      FAILED="$FAILED $pkg"
      tail -3 /tmp/puffer_pip.log | sed 's/^/      /'
    fi
  done < requirements.txt

  if ! "$PY" -c "import vosk, sounddevice, cv2, faster_whisper" >/dev/null 2>&1; then
    echo ""
    echo "  ✗ 还有东西没装上：$FAILED"
    echo "    把这一屏截图发给我。"
    read -n 1 -s -r -p "  按任意键关闭窗口"
    exit 1
  fi
  echo ""
  echo "  ✓ 装好了。"
fi

if [ ! -f config.json ]; then
  cp config.example.json config.json
fi

KEY_OK=$("$PY" -c "import json;print(1 if json.load(open('config.json'))['api_key'].strip() and not json.load(open('config.json'))['api_key'].startswith('在这里') else 0)" 2>/dev/null)

if [ "$KEY_OK" != "1" ]; then
  echo "  还差最后一步：填 API key。"
  echo ""
  echo "  我帮你把配置文件打开了，把 key 粘贴到"
  echo "      \"api_key\": \"\""
  echo "  两个引号中间，存盘（⌘S），关掉窗口回来按回车。"
  echo ""
  echo "  ⚠️  key 别发给任何人，包括帮你写代码的人。"
  echo ""
  open -e config.json
  read -n 1 -s -r -p "  填好并存盘后，按任意键继续…"
  echo ""
  "$PY" main.py --check
  echo ""
  read -n 1 -s -r -p "  按任意键继续…"
  clear
fi

echo ""
echo "  1   打字对话（稳，推荐先用这个）"
echo "  2   语音对话（直接说话，要麦克风）"
echo "  0   退出"
echo ""
read -r -p "  输入数字，回车：" MODE

case "$MODE" in
  2) "$PY" main.py --talk ;;
  0) exit 0 ;;
  *) "$PY" main.py ;;
esac

echo ""
read -n 1 -s -r -p "  按任意键关闭窗口"
