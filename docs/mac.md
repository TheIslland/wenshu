# macOS 使用与适配说明

## 一条命令

```bash
# 需要 uv（没装先跑这一行）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 从仓库安装（推荐）
uv tool install git+https://github.com/TheIslland/wenshu
wenshu
```

或者克隆后双击 `scripts/install.command`。

首次启动会：

1. 在 `~/Library/Application Support/Wenshu/` 建数据目录（权限 700）；
2. 起一个只监听 `127.0.0.1` 的服务，端口从 8765 开始，占用就顺延；
3. 自动打开浏览器。关闭用终端里的 `Ctrl+C`。

不想自动开浏览器：`wenshu --no-browser`。换端口：`wenshu --port 9000`。演示：`wenshu --demo`。

## 为什么是浏览器，不是 .app

- 纯 Python 依赖，不需要 Node、Java、Homebrew、Pandoc。
- 数据是单个 SQLite 文件，备份=复制整个目录。
- 先保证「一条命令能跑」；Tauri 壳和签名公证放二期。

Gatekeeper：从终端安装、未经 Apple 公证，首次运行如被拦，到「系统设置 → 隐私与安全性」点「仍要打开」。不要 `sudo`。

## Apple Silicon / Intel

CI 覆盖 `macos-14`（arm64）和 `macos-13`（x86）。依赖都有预编译 wheel（lxml、pypdf、python-docx、jieba 等），安装不触发本地编译。

如果 uv 报 `Failed to hardlink files`，只是缓存与目标不在同一文件系统，不影响使用；可设 `export UV_LINK_MODE=copy` 消除提示。

## 中文与路径

- 附件按 `sha256[:16].pdf` 存，避免中文长标题超过 APFS 的 255 字节文件名上限。
- 数据目录、PDF 名、导出路径支持中文与空格；文本统一 UTF-8 + NFC。
- 检索用 FTS5 trigram；若系统 SQLite 不支持，启动时自动降级为 `LIKE`，功能不崩。
- DOCX 用宋体 / Times New Roman；不依赖本机字体排版。

## 常见问题

**端口都被占用**：`wenshu --port 9100`。

**浏览器打不开**：手动访问终端打印的 `http://127.0.0.1:8765`。

**换了电脑**：复制 `~/Library/Application Support/Wenshu/` 整个目录；API key 也在里面，别公开。

**卸载**：`uv tool uninstall wenshu`；数据目录手动删。

**想接 Ollama**：设置 → 预设选「Ollama 本地」，Base URL `http://127.0.0.1:11434/v1`，模型填本机已拉取的，例如 `qwen2.5:7b`。
