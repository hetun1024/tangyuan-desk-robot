#!/bin/bash
# 把汤圆装到桌面上：编译窗口、打包成 app、设成登录时自动启动。
# 双击一次就好，以后开机她自己在。
cd "$(dirname "$0")" || exit 1

echo "==== 汤圆 · 安装到桌面 ===="
echo

# 1. 立绘图层
if [ ! -d assets/pet ] || [ -z "$(ls -A assets/pet 2>/dev/null)" ]; then
  echo "[1/4] 切图层…"
  /usr/bin/python3 build_pet.py || { echo "切图失败"; read -n1; exit 1; }
else
  echo "[1/4] 图层已存在，跳过"
fi

# 2. 编译
echo "[2/4] 编译桌面窗口…"
mkdir -p build
clang -fobjc-arc -O2 -framework Cocoa pet/PetWindow.m -o build/tangyuan_pet || {
  echo "编译失败（需要 Xcode 命令行工具：xcode-select --install）"; read -n1; exit 1; }

# 3. 打包成 app
APP="$HOME/Applications/汤圆.app"
echo "[3/4] 打包到 $APP …"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp build/tangyuan_pet "$APP/Contents/MacOS/"
cp -R assets/pet "$APP/Contents/Resources/pet"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>汤圆</string>
  <key>CFBundleExecutable</key><string>tangyuan_pet</string>
  <key>CFBundleIdentifier</key><string>cc.drobotics.tangyuan.pet</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# 4. 开机自启
echo "[4/4] 设置登录时自动启动…"
PLIST_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$PLIST_DIR"
cat > "$PLIST_DIR/cc.drobotics.tangyuan.pet.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>cc.drobotics.tangyuan.pet</string>
  <key>ProgramArguments</key><array><string>$APP/Contents/MacOS/tangyuan_pet</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict></plist>
PLIST
launchctl unload "$PLIST_DIR/cc.drobotics.tangyuan.pet.plist" 2>/dev/null
launchctl load "$PLIST_DIR/cc.drobotics.tangyuan.pet.plist" 2>/dev/null

# 5. 大脑也设成后台常驻（不用开终端）
echo "[5/5] 设置「脑子」后台常驻…"
BRAIN_LOG="$HOME/Library/Logs/tangyuan-brain.log"
PROJ="$(pwd)"
cat > "$PLIST_DIR/cc.drobotics.tangyuan.brain.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>cc.drobotics.tangyuan.brain</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>-u</string>
    <string>$PROJ/main.py</string>
    <string>--talk</string><string>--no-face</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJ</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>$BRAIN_LOG</string>
  <key>StandardErrorPath</key><string>$BRAIN_LOG</string>
</dict></plist>
PLIST
launchctl unload "$PLIST_DIR/cc.drobotics.tangyuan.brain.plist" 2>/dev/null
launchctl load "$PLIST_DIR/cc.drobotics.tangyuan.brain.plist" 2>/dev/null
echo "       日志：$BRAIN_LOG"

open "$APP"
echo
echo "装好了。她现在应该在屏幕右下角，而且可以直接说话。"
echo "  · 拖动她：按住鼠标拖"
echo "  · 关掉她：屏幕顶部菜单栏「汤圆」→ 退出"
echo "  · 说话：直接说，不用按键（第一次会问麦克风权限，点允许）"
echo "  · 卸载：删掉 ~/Applications/汤圆.app 和 ~/Library/LaunchAgents/cc.drobotics.tangyuan.*.plist"
echo
read -n1 -p "按任意键关闭窗口"
