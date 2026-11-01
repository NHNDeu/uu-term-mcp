#!/usr/bin/env bash
# macOS 上注册 uu-term MCP（用户级）。没在 Mac 上测过，出问题把报错发给 Claude。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

CLI="${UU_CLI:-}"
if [ -z "$CLI" ]; then
  CLI="$(command -v uuyc-cli || true)"
fi
if [ -z "$CLI" ]; then
  for p in /usr/local/bin/uuyc-cli /opt/homebrew/bin/uuyc-cli /Applications/*UU*.app/Contents/MacOS/uuyc-cli /Applications/*GameViewer*.app/Contents/MacOS/uuyc-cli; do
    if [ -x "$p" ]; then CLI="$p"; break; fi
  done
fi
if [ -z "$CLI" ]; then
  echo "找不到 uuyc-cli。请先装好 UU 远程并登录，然后 UU_CLI=/完整/路径/uuyc-cli ./install-mac.sh" >&2
  exit 1
fi

echo "uuyc-cli: $CLI"
"$CLI" device list || { echo "uuyc-cli 跑不通：确认 UU 远程主程序已运行并登录" >&2; exit 1; }

command -v claude >/dev/null || { echo "找不到 claude 命令" >&2; exit 1; }
claude mcp remove uu-term -s user >/dev/null 2>&1 || true
claude mcp add uu-term --scope user -e UU_CLI="$CLI" -- python3 "$HERE/server.py"
echo "已注册。新开一个 Claude 会话后，让它用 uu_exec 在穿墙上执行 hostname。"
