#!/bin/bash
# macOS: double-click to install and start Wenshu.
set -e
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "还没有安装 uv。"
  echo "请先在终端运行：curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "装好后重新双击本文件。"
  read -r -p "按回车退出…" _
  exit 1
fi

echo "正在准备文枢 Wenshu…"
uv sync
uv run wenshu
