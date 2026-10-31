# 文枢 Wenshu MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. 本计划由 Lead 统筹，四个并行 workstream 写不同目录；Lead 负责核心骨架、集成、测试与发布。

**Goal:** 交付一个可在 macOS 一条命令启动的本地 AI 论文工作台，覆盖检索、文献库、风格体检、润色、调段、方法矩阵、研究方向、流程、核引与导出，并推送到 GitHub。

**Architecture:** Python 3.12 + FastAPI + SQLite(WAL, FTS5 trigram) 单进程本地服务；Jinja2 + 原生 JS + Vditor 前端，无 Node 构建；LLM 走 OpenAI 兼容协议，规则引擎可离线工作；所有外部文献源走官方 API，PDF 用 pypdf。

**Tech Stack:** uv / FastAPI / Pydantic v2 / sqlite3 / httpx / pyalex / habanero / arxiv / semanticscholar / citeproc-py / pypdf / jieba / python-docx / pytest / respx / ruff

**Spec:** `docs/superpowers/specs/2026-10-31-wenshu-design.md`

## Global Constraints

- Python `>=3.11,<3.14`；开发与 CI 锁 3.12；提交 `uv.lock`。
- 只监听 `127.0.0.1`；所有 `/api/*`（`/api/health` 除外）必须校验 `X-Wenshu-Token`。
- 数据目录用 `platformdirs`；macOS 默认 `~/Library/Application Support/Wenshu/`；禁止硬编码路径分隔符。
- 不引入 Node/Java/Homebrew/Pandoc 运行时依赖；前端静态资源随包分发。
- 不复制 GPL/AGPL/无 License/非商用许可代码；依赖只用 MIT/BSD/Apache-2.0/BlueOak。
- 不生成、不补全任何未在检索结果或本地库中出现过的文献；缺证据一律进 `gaps`。
- 「去 AI 味」只做文风 lint，不承诺降低 AIGC 检测率。
- 中文文本统一 UTF-8 + NFC；附件文件名 `sha256[:16].pdf`。
- 每个 workstream 只改自己 write scope 内的文件；不运行 `git add/commit/push`（Lead 统一提交）。
- 测试不得依赖公网：外部 API 用 respx/monkeypatch；LLM 用 `FakeLLM`。

## Review Focus

1. **空输入/超长输入**：空段落、10 万字文档、单段 2 万字——分析/导出不得 500 或卡死。
2. **中文路径与文件名**：含空格、中文、emoji 的数据目录/PDF 名——附件保存、导出、FTS 不得崩。
3. **无 key / 无网络**：未配置 LLM、断网检索、Crossref 429——必须降级并给出人话错误，UI 不白屏。
4. **引用安全**：`[@missing]`、重复 DOI、无 DOI 文献、未核引导出——必须显式报错或列入清单，不能静默。
5. **并发写文档**：两个标签页同时保存——版本号冲突返回 409，不得静默覆盖。

---

## Task 0: 核心骨架（Lead）

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE`, `NOTICE.md`, `.github/workflows/ci.yml`
- Create: `src/wenshu/{__init__,__main__,cli,config,db,models,security,errors,llm,app}.py`
- Create: `src/wenshu/api/{__init__,deps,health,projects,documents,search,library,style,polish,paragraphs,methods,direction,workflow,citations,export,settings}.py`（其余为占位 router）
- Create: `src/wenshu/templates/{base,index,project,settings,404}.html`、`static/css/base.css`、`static/js/{api,app}.js`
- Test: `tests/{conftest,test_health,test_db,test_security,test_projects,test_documents}.py`

**Interfaces (Produces):**
- `config.RuntimeConfig(data_dir: Path, port: int, token: str, demo: bool)`
- `db.Database(path: Path)`：`.connect()`, `.init()`, `.query(sql, params) -> list[sqlite3.Row]`, `.execute(sql, params) -> int`, `.tx()`
- `models`：`Project`, `Document`, `Ref`, `SearchHit`, `StyleFinding`, `StyleReport`, `RewriteResult`, `MethodRow`, `TaskItem`, `CitationCheck`, `DirectionCard`
- `llm.LLMClient.chat(messages, *, json_mode=False, max_tokens=2000, temperature=0.3) -> str`；`LLMClient.chat_json(messages, schema, *, retries=1) -> BaseModel`；`FakeLLM`
- `app.create_app(cfg) -> FastAPI`；`security.require_token(request)`
- 统一错误体 `{"error": {"code", "message", "detail"}}`

- [ ] 写 `pyproject.toml`（hatchling，entry point `wenshu`，包含 templates/static/csl）、`.gitignore`（数据目录、`.venv`、`__pycache__`、`*.db`、`tmp/`）
- [ ] 写 `db.py` 建表 SQL（design §8 全部表 + `refs_fts` trigram + `schema_meta`），启动自检 trigram，失败降级 LIKE
- [ ] 写 `app.py` 组装：静态、模板、token 中间件、异常处理、页面路由、include 全部 router
- [ ] 写 `cli.py`：`serve`（默认）、`--port/--data-dir/--no-browser/--demo`、端口顺延、自动开浏览器
- [ ] 测试：health、token 401、项目 CRUD、文档保存 409、schema 幂等
- [ ] 验证：`uv sync && uv run pytest -q && uv run wenshu --no-browser` + `curl /api/health`

## Task 1: 检索与文献库（teammate `search-library`）

**Files:**
- Create: `src/wenshu/services/search/{__init__,base,openalex,crossref,semantic_scholar,arxiv,wanfang,zotero,dedupe}.py`
- Create: `src/wenshu/services/{library,importers,pdf}.py`
- Modify: `src/wenshu/api/{search,library}.py`
- Test: `tests/{test_search_adapters,test_search_api,test_library,test_importers,test_pdf}.py`

**Interfaces:**
- Consumes: `db.Database`, `models.SearchHit`, `models.Ref`, `llm` 不涉及
- Produces:
  - `search.ADAPTERS: dict[str, SearchAdapter]`
  - `SearchAdapter.search(query, *, limit=20, year_from=None, year_to=None, language=None) -> list[SearchHit]`
  - `search.search_all(db, query, sources, **filters) -> tuple[list[SearchHit], dict[str,str]]`（并行、超时 15s、错误按源捕获）
  - `dedupe.dedupe(hits) -> list[SearchHit]`（DOI→归一化标题+年）
  - `library.upsert_ref(db, hit, project_id) -> int`（全局 refs + project_refs，返回 ref_id）
  - `library.list_refs(db, project_id=None, q=None, status=None, tag=None) -> list[dict]`
  - `importers.import_ris(text) / import_bibtex(text) -> list[SearchHit]`；`import_doi(doi) -> SearchHit`
  - `pdf.extract_text(data: bytes) -> tuple[str, dict]`（pypdf；损坏 PDF 抛 `PdfError`）
  - API：`POST /api/search`、`GET /api/search/history`、`POST /api/search/doi`、`GET /api/refs`、`POST /api/refs/import`、`POST /api/refs/{id}/attach`、`PATCH /api/refs/{id}`、`GET /api/refs/{id}/text?q=`、`GET /api/zotero/status`、`POST /api/zotero/import`

- [ ] 适配器共通：超时、429/5xx 重试一次、归一化作者/年份/DOI/语言，错误信息人话化
- [ ] OpenAlex 用 pyalex；Crossref 用 habanero；arXiv 用 arxiv；S2 用 semanticscholar；万方仅实验开关
- [ ] 去重与入库（DOI 唯一、标题 Jaccard ≥0.92 + 同年视为重复；合并保留更全字段）
- [ ] RIS/BibTeX/DOI/PDF 导入；Zotero 本地 API 只读；附件 hash 命名 + 全文入库 + FTS
- [ ] 测试：respx 模拟四源、去重、编码（中文/日文/花括号）、损坏 PDF、Zotero 未启动降级

## Task 2: 风格体检 / 润色 / 调段（teammate `style-engine`）

**Files:**
- Create: `src/wenshu/services/style/{__init__,metrics,rules,engine,baseline}.py`
- Create: `src/wenshu/services/{rewrite,polish,paragraphs}.py`
- Create: `src/wenshu/prompts/{style_rewrite,polish,paragraph_transform}.md`
- Modify: `src/wenshu/api/{style,polish,paragraphs}.py`
- Test: `tests/{test_style_metrics,test_style_rules,test_style_engine,test_style_api,test_polish,test_paragraphs}.py`

**Interfaces:**
- Consumes: `db.Database`, `llm.LLMClient/FakeLLM`, `models.*`
- Produces:
  - `metrics.compute(text) -> dict[str,float]`（句长CV、段长CV、连接词密度/TTR、四字连排、套话、意义拔高、虚化动词、具体性锚点、引号破折号密度、的链）
  - `engine.analyze(text, *, baseline=None, llm=None) -> StyleReport`
  - `engine.apply_safe_fixes(text, findings) -> dict{revised, applied, diff, warnings}`
  - `rewrite.rewrite(text, *, mode, llm, context_before="", context_after="", terms=None, citations=None, instruction="") -> RewriteResult`
  - `polish.polish(...)` 复用 rewrite，mode ∈ {academic, concise, cohesive, concrete}
  - `paragraphs.transform(text, *, op, llm, context_before="", context_after="", role="analysis", max_delta=0.2, evidence=None, terms=None) -> RewriteResult`（op ∈ compress/expand/reorder/argument）
  - `baseline.build(texts) -> dict`；`baseline.score(metrics, baseline) -> dict`
  - API：`POST /api/style/analyze`、`/fix`、`/rewrite`、`/baseline`；`POST /api/polish`；`POST /api/paragraphs/transform`
- 硬约束：引用标记 `[n]`/`[@key]`、引文、数字、术语表不得改动；±20% 字数；缺证据进 gaps；输出字符级 diff。

- [ ] 16 条规则 + 冷启动阈值；个人基线 z-score；分数只叫「风格风险」
- [ ] 安全修正只做删套话/还原虚化动词/改标点，逐条 span，可回退
- [ ] LLM 契约：严格 JSON、超时 60s、失败重试 1 次、二次扫描拒绝引入新命中
- [ ] 调段 JSON：`revised/ops/gaps/warnings/diff`；校验引用与数字保全，否则拒绝
- [ ] 测试：规则黄金样本（AI 味/人味各 3 段）、空文本、超长段、无 key 降级、引用保全、±20%

## Task 3: 方法矩阵 / 研究方向 / 核引 / 导出 / 流程（teammate `knowledge`）

**Files:**
- Create: `src/wenshu/services/{methods,direction,citations,exporters,workflow}.py`
- Create: `src/wenshu/prompts/{method_extract,direction}.md`
- Create: `src/wenshu/static/csl/*.csl`（GB/T 7714-2015 numeric + APA 7）
- Modify: `src/wenshu/api/{methods,direction,citations,export,workflow}.py`
- Test: `tests/{test_methods,test_direction,test_citations,test_export,test_workflow}.py`

**Interfaces:**
- Consumes: `db`, `models`, `llm`, `library.list_refs`
- Produces:
  - `methods.extract(db, project_id, ref_ids, llm) -> dict{rows, extracted, skipped}`
  - `methods.matrix(db, project_id) -> dict{rows, trend:[{year,count}], method_trend, conflicts}`
  - `direction.explore(db, topic, *, llm, project_id=None, years=10, language=None) -> dict{stats, cards, evidence_refs, warnings}`
  - `citations.verify(db, ref_ids=None, *, client=None) -> list[dict{ref_id,status,detail}]`
  - `citations.format_refs(refs, style="gbt7714") -> str`（citeproc-py + CSL，失败回退内置 formatter 并 warn）
  - `exporters.docx(project, document, refs, style) -> bytes`；`markdown(...) -> str`；`bibtex(refs) -> str`；`ris(refs) -> str`
  - `workflow.apply_template(db, project_id, template) -> list[TaskItem]`；`gate(db, project_id) -> dict{ok, blockers}`
  - API：`POST /api/methods/extract`、`GET /api/methods/matrix`、`PATCH /api/methods/rows/{id}`、`POST /api/direction/explore`、`POST /api/citations/verify`、`GET /api/citations/format`、`POST /api/export/{fmt}`、`GET/POST/PATCH/DELETE /api/tasks`、`POST /api/workflow/template`、`GET /api/workflow/gate`

- [ ] 方法词典（文本分析/内容分析/话语分析/民族志/深度访谈/问卷/个案/比较/实验/计算/混合）+ LLM 证据句；矩阵可编辑
- [ ] 趋势：本地库年份 + OpenAlex group_by 年度；冲突检测同作者样本不同结论
- [ ] 核引：DOI→Crossref/OpenAlex 比对标题/年/作者；无 DOI 标 `no_doi`；批量
- [ ] CSL：下载并提交两份样式，NOTICE 署名 CC BY-SA 3.0；citeproc 失败回退
- [ ] DOCX：宋体/Times New Roman、小四、1.5 倍、标题层级、参考文献表、未核引清单
- [ ] 流程模板（开题/论文/投稿）+ 门禁 + 周报
- [ ] 测试：方法抽取（FakeLLM）、趋势、核引三分支、GB/T 黄金输出、docx 可被 python-docx 重新打开、门禁

## Task 4: 前端工作台（teammate `frontend`）

**Files:**
- Create: `src/wenshu/templates/project.html`
- Create: `src/wenshu/static/css/app.css`
- Create: `src/wenshu/static/js/{workspace,library,search,style,polish,paragraphs,methods,direction,workflow}.js`
- Create: `src/wenshu/static/vendor/vditor/*`（若集成；否则不用）
- Modify: `src/wenshu/static/js/api.js`（仅新增 helper，不改签名）
- Test: `tests/test_pages.py`（路由 200、关键 DOM 标记存在；不跑浏览器）

**Interfaces:**
- Consumes: Task 0 的 `window.WENSHU = {token, projectId}`、`api.js` 的 `api.get/post/patch/del/upload`；Task 1–3 的 API JSON
- Produces: 页面内 tab：概览 / 写作 / 文献 / 检索 / 体检 / 润色 / 段落 / 方法 / 方向 / 流程 / 设置

- [ ] 基础布局：左侧项目导航 + 顶部状态（LLM 是否配置、字数）+ tab 容器
- [ ] 写作：文档列表、Vditor 或 textarea、自动保存（1.5s debounce）、快照、段落卡片操作
- [ ] 文献/检索：结果卡、批量入库、筛选、导入弹窗、PDF 上传、Zotero 按钮
- [ ] 体检/润色/段落：风险仪表、证据高亮、safe fix 预览、diff 三色、接受/拒绝
- [ ] 方法/方向/流程：矩阵表、SVG 年份柱状图、问题卡、看板拖拽或状态按钮
- [ ] 空状态/错误态/加载态/无 key 提示；中文排版与暗色不做，浅色纸感
- [ ] 测试：`/p/{id}` 200、包含各 tab 标记、静态资源 200、无外链 CDN

## Task 5: 集成、演示与发布（Lead）

**Files:**
- Create: `README.md`, `NOTICE.md`, `docs/mac.md`, `docs/api-contract.md`, `scripts/dev.sh`, `scripts/install.command`, `examples/demo/*`, `skills/*/SKILL.md`
- Modify: `pyproject.toml`, `.github/workflows/ci.yml`
- Test: `tests/test_smoke.py`, `tests/test_demo.py`

- [ ] 演示项目（虚构：短视频与地方感）+ FakeLLM 演示模式
- [ ] README：截图、安装、Mac 说明、LLM 配置、合规边界、架构图
- [ ] skills：5 个 SKILL.md，可被 Claude/Codex 加载
- [ ] CI 四平台；`uv lock`；`ruff check`；`pytest`
- [ ] 全量测试 + 手工冒烟（起服务、建项目、检索 mock、体检、导出）
- [ ] GitHub：`gh repo create TheIslland/wenshu --public`，push，topics，release v0.1.0

## Verification

```bash
uv sync --all-extras
uv run ruff check .
uv run pytest -q
uv run wenshu --demo --no-browser
curl -s http://127.0.0.1:8765/api/health
```

完成标准：8 条人工验收（design §13）全过；CI 四平台绿；仓库公开可克隆；README 一条命令可复现演示。
