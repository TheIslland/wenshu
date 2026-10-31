# 第三方依赖与许可说明

文枢 Wenshu 本体以 MIT 许可发布。以下依赖/资源由各自作者提供，按其原许可使用：

## 运行时依赖（Python）

| 包 | 许可 | 用途 |
|---|---|---|
| FastAPI | MIT | HTTP 框架 |
| Uvicorn | BSD-3-Clause | ASGI 服务器 |
| Jinja2 | BSD-3-Clause | 模板 |
| Pydantic | MIT | 数据校验 |
| httpx | BSD-3-Clause | HTTP 客户端 |
| pyalex | MIT | OpenAlex 检索 |
| habanero | MIT | Crossref 检索 |
| arxiv | MIT | arXiv 检索 |
| semanticscholar | MIT | Semantic Scholar 检索 |
| citeproc-py | BSD-2-Clause-Views | CSL 引用渲染 |
| lxml | BSD-3-Clause | XML 处理（citeproc/arxiv 依赖） |
| bibtexparser | MIT | BibTeX 解析 |
| rispy | MIT | RIS 解析 |
| pypdf | BSD-3-Clause | PDF 文本抽取 |
| jieba | MIT | 中文分词 |
| python-docx | MIT | DOCX 导出 |
| platformdirs | MIT | 跨平台数据目录 |

## 样式文件

- `src/wenshu/static/csl/china-national-standard-gb-t-7714-2015-numeric.csl`
  来自 [zotero-chinese/styles](https://github.com/zotero-chinese/styles)，
  以 **CC BY-SA 3.0** 许可分发，原样未修改。署名：zotero-chinese/styles contributors。
- `src/wenshu/static/csl/apa.csl` 来自
  [citation-style-language/styles](https://github.com/citation-style-language/styles)，
  以 **CC BY-SA 3.0** 许可分发，原样未修改。

CC BY-SA 3.0 全文：https://creativecommons.org/licenses/by-sa/3.0/

## 前端资源

- [Vditor](https://github.com/Vanessa219/vditor)（MIT）：中文 Markdown 编辑器，
  若打包则原样分发其 `dist/` 与 LICENSE。

## 仅借鉴思路、未复制代码的项目

paper-qa（Apache-2.0）、STORM（MIT）、local-deep-research（MIT）、
gpt_academic（GPL-3.0，仅交互参考）、Humanizer-zh（MIT）、
academic-humanizer（MIT）、ai-write-flow（MIT）、cnki-aigc（MIT）、
aigc-reduce（MIT）、blader/humanizer（MIT）。

以下项目**未**使用：PyMuPDF（AGPL-3.0）、Zotero 本体（AGPL-3.0）、
AI-Scientist 系列（自定义许可）、paper-search-mcp（含可选 Sci-Hub 回退）。
