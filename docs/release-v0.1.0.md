# 文枢 Wenshu v0.1.0

本地优先的中文文科科研文献与写作工作台。找文献、建库、体检文风、润色调段、做方法矩阵、核引用、导 docx——数据都在这台电脑上。

## 这一版能做什么

- **研究方向**：检索统计 + 本地库缺口，生成 3–5 张带证据边界的问题卡。
- **文献检索**：OpenAlex / Crossref / Semantic Scholar / arXiv；DOI 直查；万方接口保留为实验性。
- **文献库**：全局库 + 项目关联；RIS/BibTeX/DOI/PDF/Zotero 导入；FTS5 trigram 全文检索。
- **写作台**：Markdown、章节大纲、自动保存（乐观锁）、快照回滚、`[@key]` 引用。
- **风格体检**：16 条段落级规则（13 条离线 + 3 条 LLM）、证据 span、风险分、安全修正、个人基线。
- **文笔润色**：学术化 / 简洁 / 衔接 / 具体化；引用、数字、术语锁定。
- **段落调整**：压缩 / 扩写 / 重排 / 补论证；±20%；缺证据进 gaps。
- **方法矩阵**：方法/数据/样本/理论/结论/局限；年份趋势；冲突标记。
- **研究流程**：开题/论文/投稿模板、看板、导出前门禁。
- **交付**：DOI 核验、GB/T 7714-2015、APA 7、BibTeX/RIS、DOCX、未核引清单。

## 安装

```bash
# 需要 uv
uv tool install git+https://github.com/TheIslland/wenshu
wenshu
```

或者克隆后：

```bash
git clone https://github.com/TheIslland/wenshu.git
cd wenshu
uv sync
uv run wenshu --demo
```

Mac 用户看 [docs/mac.md](docs/mac.md)。

## 验证

- 250+ 个测试通过；`ruff check .` 通过。
- CI：Ubuntu、macOS 14 (arm64)、Windows × Python 3.12。
- 干净 wheel 安装后 `wenshu --version` 与演示服务均验证通过。

## 边界

- 「风格体检」是文风 lint，不针对任何 AIGC 检测系统，不承诺降低检测率。
- 不爬知网/维普/Google Scholar，不使用 Sci-Hub；中文库靠官方导出、Zotero 与本机 PDF。
- AI 输出不可信：文献线索必须核验，缺证据标「待补」。
- v0.1 用文中编号 + 文末参考文献，暂不做页下脚注。

## 后续

页下脚注、CSL 全样式、GROBID、PDF 标注、Tauri 2 签名 `.app`、向量检索。
