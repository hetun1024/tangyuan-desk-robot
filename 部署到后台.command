#!/bin/bash
# 把「脑子」部署到 ~/tangyuan（Downloads 以外的位置），
# 因为 macOS 不允许后台进程读 ~/Downloads —— 桌宠要能自己拉起她，就必须搬出来。
#
# 改了代码之后，双击这个文件一次就同步过去。
set -e
cd "$(dirname "$0")" || exit 1
DEST="$HOME/tangyuan"

echo "==== 部署到 $DEST ===="
mkdir -p "$DEST"
rsync -a --delete \
  --exclude 'assets/' --exclude '.git/' --exclude '__pycache__/' \
  --exclude 'out/' --exclude 'build/' --exclude '*.pyc' \
  ./ "$DEST/"

# 记忆和情绪跟着走：第一次部署时把现有的拷过去，之后不覆盖
if [ ! -f "$DEST/data/profile.json" ] && [ -d ./data ]; then
  mkdir -p "$DEST/data"
  cp -R ./data/. "$DEST/data/" 2>/dev/null || true
fi

echo "已同步：$(du -sh "$DEST" | cut -f1)"
echo "现在桌宠菜单里的「对话模式」可以直接用了。"
read -n 1 -s -r -p "按任意键关闭"
