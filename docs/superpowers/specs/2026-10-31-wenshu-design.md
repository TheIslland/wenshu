# 文枢 Wenshu · 文科科研文献与写作工作台

> 设计文档 v0.1｜2026-10-31｜状态：待你拍板
> 工作名「文枢」取自「文之枢纽」，仓库名暂定 `wenshu`，可改。

## 1. 为什么做

你手上这篇日本偶像/拟像论文，已经把真实工作流暴露得很清楚：开题报告迭代到 v4、19 条参考文献逐条核查、理论卡片分五个文件维护、最后还要转 docx。这套流程里最贵的不是「写」，是**找、核、对**。

四个断点：

1. **检索散**：中文库没有公开 API，英文库各一套；OpenAlex 对中文期刊覆盖很差，知网只能人肉。
2. **入库断**：PDF、元数据、笔记、引用格式是四套系统，Zotero 和 Word 之间还要来回复制。
3. **写作空**：通用 AI 产出「正确的废话」——抽象、对仗、没有材料锚点，改起来比重写还累。
4. **核引难**：AI 会编文献；导出前没人逐条核 DOI、卷期、页码。

产品承诺只有三句：

- **每一句判断都能挂上材料**（挂不上就标「待补」，不许编）。
- **每一本文献都能核到源头**（DOI/Crossref，核不到就标红）。
- **每一次改写都能 diff、能回滚**（不做全篇一键重写）。

## 2. 目标 / 非目标 / 反目标

**目标**
- 单人在自己电脑上跑，Mac 一条命令启动，数据全本地。
- 覆盖：研究方向 → 检索 → 入库 → 阅读 → 综述 → 写作 → 风格体检 → 润色 → 调段 → 方法对比 → 核引 → 导出 → 投稿流程。
- 无 LLM 也能用（规则引擎、文献库、导出全离线）；有 LLM 时增强，不绑架。
- 开源、可复用、引用与许可干净。

**非目标**
- 不替代 Zotero / Word / Obsidian；做它们之间的工作台。
- 不做「降低 AIGC 检测率」的承诺，不卖检测规避。
- 不内置知网/维普/Google Scholar 爬虫。
- 不做多人协作、账号体系、云端同步（v1）。
- 不做通用聊天机器人。

**反目标（做到也算失败）**
- 生成任何一条未在检索结果或本地库中出现的文献。
- 整篇重写抹掉作者声音，产出更浓的 AI 味。
- 把 API key 上传到任何服务器；默认收集任何遥测。
- 为了功能数量牺牲「可核验」。

## 3. 主用户与主场景

主用户：中文文科硕博/青年学者，研究文化研究、传播、电影、符号学一类；会自己配 LLM API（DeepSeek/OpenAI 兼容/Ollama），但不想碰服务器。

一条主路径：

```
新建项目 → 研究方向（3-5 个问题卡） → 检索/导入文献 → 入库打标
→ 读 PDF/做笔记 → 生成综述地图 → 搭大纲 → 逐段写
→ 风格体检（去 AI 味） → 润色/调段（diff 接受） → 核引
→ 导出 docx/参考文献 → 流程看板跟投稿
```

## 4. 产品形态

本地 Web 工作台，不是 Electron 客户端。

```bash
# 安装（Mac / Windows / Linux 通用）
uv tool install git+https://github.com/TheIslland/wenshu
wenshu            # 起服务并自动打开浏览器
```

- 只监听 `127.0.0.1`，端口 8765 起，占用则顺延。
- 数据目录：macOS `~/Library/Application Support/Wenshu/`，Windows `%APPDATA%\Wenshu\`，Linux `$XDG_DATA_HOME/wenshu/`；`wenshu --data-dir` 可改。
- 单用户，无登录；启动时生成一次性本地 token，页面与 API 都带，防本机其他网页 CSRF。
- 首次启动进引导页：选 LLM 预设（可跳过）→ 建第一个项目。

## 5. 模块规格

### 5.1 研究方向

**输入**：领域/现象/理论关键词、年份范围、语种、本地库已有文献。
**做**：拉 OpenAlex/Semantic Scholar 的年度产量、Top 期刊/作者/概念；对照本地库找空白；LLM 生成 3–5 张问题卡。
**问题卡字段**：研究问题、既有解释的裂缝、所需材料、可行方法、主要风险、难度、新颖度、支撑文献 ID。
**硬约束**：支撑文献只能来自本次检索结果或本地库；没有就写「待检索」，不许编。
**输出**：问题卡可一键建项目、拆成流程任务。
**降级**：无 LLM 时只给检索统计 + 内置问题模板（现象/机制/比较/接受史四类）。

### 5.2 文献检索

**源**：OpenAlex、Crossref、Semantic Scholar、arXiv；万方（实验性，需用户自备 `X-App-Key`）；DOI 直查；Zotero 本地库只读。
**功能**：关键词/作者/年份/语种/类型过滤；跨源去重（DOI → 归一化标题+年）；结果卡显示被引数、摘要、来源；单条/批量入库；查询历史。
**合规**：不爬知网、维普、Google Scholar；提供「在知网/万方/Scholar 打开」外链。
**缓存**：查询结果本地缓存 24h，失败可重试。
**降级**：网络不可用时只显示本地库与手动导入。

### 5.3 文献库

**字段**：标题、作者、年份、期刊/出版社、卷期页、DOI、URL、摘要、类型、语种、标签、笔记、阅读状态（收件箱/在读/已读/已引）、PDF、全文、引用键。
**导入**：RIS、BibTeX、DOI、PDF（提取元数据+全文）、Zotero 本地 API、CNKI 导出的 NoteExpress/RIS 文件。
**全文检索**：SQLite FTS5 + trigram（中文子串可用）；无 trigram 时降级 LIKE。
**去重**：DOI 优先；无 DOI 用归一化标题+年份；合并时保留更全字段。
**导出**：BibTeX、RIS、CSV。
**附件**：按 `sha256[:16].pdf` 存，避免中文长文件名在 macOS 上超 255 字节。

### 5.4 写作台

- 项目 → 文档（Markdown）→ 章节树；自动保存 + 手动快照；字数统计。
- 编辑器用 **Vditor**（MIT，中文 Markdown 三模式，静态资源随仓库分发、不走 CDN）；集成受阻则回退原生 textarea，功能不变。
- 段落卡片视图：按空行/标题切块，每块可「体检 / 润色 / 调段 / 加引用」。
- 引用插入：`[@bibkey]` 或 `[1]`；导出时解析成编号与参考文献表；找不到 key 直接报错，不静默。
- 术语表：项目级锁定术语，改写时禁止替换。
- 只做 Markdown，不做富文本 WYSIWYG（v1）。

### 5.5 风格体检（去 AI 味）

**定位**：写作质量体检，不是 AIGC 检测器。UI 明写「不针对任何检测系统，不承诺降低 AI 率」。

**规则引擎**：16 条段落级规则（来自调研，见 §7），输出：
- 0–100「风格风险分」+ 等级（低/中/高）；
- 每条命中给 `{规则, 严重度, 原文片段, 位置, 人话解释, 建议}`；
- 可自动的「安全修正」与需作者确认的「建议改写」分开。

**个人基线**：粘贴 3–5 篇本人已发表/认可文本，按指标算均值方差，之后用 z-score 判断，避免学科误报；无基线用冷启动阈值并标注「默认阈值」。

**LLM 复审**：只对规则筛出的高风险段落做语义判断——论证跳跃、概念漂移、让步缺失、正确废话；必须输出原文证据句，不许泛泛而谈。

**二次扫描**：任何改写结果重新过一遍规则，若引入新问题则拒绝并提示。

### 5.6 文笔润色

**输入**：选中文本/整段、模式（学术化 / 简洁 / 衔接 / 具体化）、上下文前后段、术语表、引用列表。
**约束**：不动引用编号、引文原文、数字、术语；字数变动 ≤ ±15%；至少保留 1 句作者判断；禁止同义词轮换、禁止新增比喻/排比。
**输出**：改写文本 + 逐条修改理由 + 字符级 diff；接受 / 拒绝 / 再来一版；接受时写快照。

### 5.7 段落调整

**四类操作**：压缩（删套话/合并同义）、扩写（只补证据与解释，不补形容词）、重排（主题句前置、旧信息→新信息）、补论证（断言→证据→解释→让步）。
**输入**：段落、前后段、章节角色（综述/理论/个案/结论）、目标、证据池、最大变动比例。
**输出 JSON**：`revised`、`ops[]`、`anchors[]`、`gaps[]`、`preserved[]`、`diff`。
**硬约束**：不新增原文与证据池之外的事实/数字/文献/场景；缺证据进 `gaps`；功能不变（综述段不能改成个案段）；±20%；可回滚。

### 5.8 方法对比与趋势

**抽取**：从摘要/笔记提取 `{方法, 数据来源, 样本, 理论视角, 核心结论, 局限}` + 证据原句；规则词典打底，LLM 补充；每条可编辑、可溯源。
**矩阵**：行=文献，列=维度；支持按方法/年份/理论筛选；导出 CSV/Markdown。
**趋势**：本地库年份分布 + OpenAlex 年度计数；方法词频随时间；同一作者/样本的结论冲突自动标黄。
**降级**：无 LLM 时只做词典命中与年份统计，明确标注「未抽取」。

### 5.9 研究流程

- 模板：开题、论文、投稿（阶段+任务+依赖+默认截止）。
- 看板：待办/进行中/完成；任务可挂文献、文档、问题卡。
- 门禁：导出前检查「未核引 / 高风险段未处理 / 未解决 gaps」，列清单，可强制导出但必须勾选确认。
- 周报：一键生成本周完成/下周计划 Markdown。

### 5.10 引用核验与导出

**核验**：用 DOI 查 Crossref/OpenAlex，比对标题、年份、作者；状态：已核 / 不匹配 / 未找到 / 无 DOI；批量核验，结果写库。
**格式**：**citeproc-py + CSL**（不手拼字符串）。GB/T 7714-2015 样式取自 `zotero-chinese/styles`（CC BY-SA 3.0，原样分发并署名），APA 7 用官方样式；BibTeX、RIS。
**导出**：Markdown、DOCX（宋体/Times New Roman、小四、1.5 倍行距、标题层级、参考文献表）；导出时附「未核引清单」。
**限制**：v1 用文中编号+文末参考文献，不做页下脚注（python-docx 原生不支持脚注，硬做要改 XML，风险高）；脚注列入 v1.1。

## 6. 技术架构

```
浏览器（Jinja2 页面 + 原生 JS 模块，无 Node 构建）
        │  fetch / JSON + 本地 token
FastAPI (uvicorn, 127.0.0.1)
 ├─ api/            路由：projects docs search library style polish paragraphs methods direction workflow citations export settings
 ├─ services/       业务：检索适配器、文献、规则引擎、LLM、方法、导出
 ├─ prompts/        提示词契约（Markdown + JSON Schema）
 └─ SQLite (WAL)    FTS5 trigram；附件与全文在数据目录
外部：OpenAlex / Crossref / S2 / arXiv / 万方(可选) / Zotero 本地 API / OpenAI 兼容 LLM
```

**选型理由**
- 全部依赖都有 macOS arm64 / Windows 预编译 wheel（含 lxml），安装不触发本地编译；无 Node 构建、无 Java。
- 检索用成熟库而不是自写适配层：`pyalex`（OpenAlex）、`habanero`（Crossref）、`arxiv`、`semanticscholar`，四者均为 MIT 且纯 Python。
- 前端不引入构建链：Jinja2 + 原生 JS + Vditor 静态资源，改完刷新即可；对单机工具足够。
- SQLite 单文件，备份=复制一个文件；FTS5 trigram 解决中文子串检索。
- PDF 用 **pypdf**（BSD）而不是 PyMuPDF（AGPL），避免许可污染；版式复杂的 PDF 可后续接 GROBID（可选服务）。
- 引用用 **citeproc-py + CSL**，不手拼 GB/T 字符串；样式文件单独放 `static/csl/` 并署名。
- LLM 只走 OpenAI 兼容协议，预设 DeepSeek / OpenAI / Moonshot / 智谱 / Ollama；用户可填任意 base_url。

**LLM 契约**
- 所有结构化任务返回严格 JSON（pydantic 校验），失败重试 1 次，再失败降级到规则结果并明示。
- 检索到的摘要/正文按「数据」包裹进提示词，防提示注入；模型不能调用工具、不能访问网络。
- 每次调用写 `ai_logs`（任务、模型、耗时、token、成功与否），不记录 key。
- 测试与演示用 `FakeLLM`，无 key 也能跑通全流程。

## 7. 风格规则引擎（16 条）

指标全部段落级、可解释；分数 = Σ(权重×命中强度)，映射 0–100。

| 规则 | 检测 | 冷启动阈值 | 处理 |
|---|---|---|---|
| 句长变异 | 句长 CV | <0.38 告警 | 拆/并句 |
| 连续同长句 | 相邻差≤8字且≥4句 | 命中 | 插短句/长句 |
| 段长均匀 | 段长 CV（≥5段） | <0.30 | 按论证单元重切 |
| 连接词密度 | 词表计数/千字 | >20 或单段≥3 | 能删就删，改隐性衔接 |
| 连接词多样性 | 唯一/总数 | <0.55 且密度>10 | 减总量，不换同义词 |
| 四字格/三连 | 连续四字结构、三项同构 | ≥1/段 | 留一项，其余具体化 |
| 总分总套话 | 首先/综上/由此可见 | ≥2/节 | 删壳 |
| 意义拔高 | 标志着/体现了/深刻/彰显 | ≥2/千字 | 停在事实或给机制 |
| 假深刻否定 | 不是X而是Y/与其说 | ≥1/千字 | 还原直接判断 |
| 破折号/装饰引号 | 密度 | 破折号>1.5/千字 | 改冒号/句号 |
| 虚化动词/性化度 | 进行+名词、X性/X化 | ≥4/千字 | 还原动词 |
| 具体性缺失 | 年份/数字/书名号/引用标记密度 | 低于阈值 | **不生成**，标「待补材料」 |
| 「的」字链 | 单句≥4 个「的」 | 命中 | 拆句 |
| 论证跳跃* | 判断句无锚点 | LLM 逐段 | 补锚点或降级为假设 |
| 概念漂移* | 术语前后不一致 | LLM | 统一术语表 |
| 让步缺失* | 全段无反例/限定 | LLM | 补最强反例+回应 |

\* 需 LLM；无 LLM 时不出这三条，不假装测过。

**明确不做**：TTR 当 AI 判据、同义词轮换、整篇重写、输出「AI 概率」。

## 8. 数据模型（SQLite）

```
projects(id, name, field, question, description, status, created_at, updated_at)
documents(id, project_id, title, kind, content_md, word_count, updated_at)
snapshots(id, document_id, content_md, reason, created_at)
refs(id, doi, title, authors_json, year, venue, volume, issue, pages, type,
     language, abstract, url, source, source_id, bibkey, pdf_path, fulltext_path,
     tags_json, note, status, created_at)          -- 全局库
project_refs(project_id, ref_id, relevance, added_at)
searches(id, project_id, source, query, filters_json, count, created_at)
style_runs(id, project_id, document_id, text_hash, score, findings_json, baseline_json, created_at)
rewrites(id, project_id, document_id, mode, source_text, result_text, ops_json,
         provider, model, status, created_at)
method_rows(id, project_id, ref_id, method, data, sample, theory, finding,
            limitation, evidence_json, updated_at)
tasks(id, project_id, stage, title, status, due, notes, sort, created_at)
citation_checks(id, ref_id, status, detail_json, checked_at)
ai_logs(id, project_id, task, provider, model, ms, prompt_tokens, completion_tokens, ok, error, created_at)
settings(key, value)
```

全局 `refs` + `project_refs`，避免一篇文献在多个项目重复导入。

## 9. API 契约（节选）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 版本、数据目录、LLM 是否配置 |
| GET/POST | `/api/projects` | 列表/新建 |
| GET/PATCH/DELETE | `/api/projects/{id}` | 详情/改/删 |
| GET/POST | `/api/projects/{id}/documents` | 文档 |
| PUT | `/api/documents/{id}` | 保存正文（带版本号，冲突 409） |
| POST | `/api/documents/{id}/snapshots` | 快照 |
| POST | `/api/search` | `{sources[], query, filters}` → 归一化结果+去重 |
| POST | `/api/library/import` | DOI/RIS/BibTeX/PDF/Zotero |
| GET/POST/PATCH | `/api/refs` | 文献库 |
| POST | `/api/refs/{id}/pdf` | 上传 PDF 并抽全文 |
| POST | `/api/style/analyze` | 规则体检 |
| POST | `/api/style/rewrite` | 安全修正 / LLM 改写 |
| POST | `/api/style/baseline` | 个人基线 |
| POST | `/api/polish` | 润色 |
| POST | `/api/paragraphs/transform` | 四类调段 |
| POST | `/api/methods/extract` | 方法抽取 |
| GET | `/api/methods/matrix` | 矩阵+趋势 |
| POST | `/api/direction/explore` | 研究方向 |
| GET/POST/PATCH | `/api/tasks` | 流程 |
| POST | `/api/citations/verify` | 批量核引 |
| POST | `/api/export/{fmt}` | md/docx/bibtex/ris |
| GET/PUT | `/api/settings` | 设置（key 不回显） |

所有写接口校验本地 token；错误统一 `{code, message, detail?}`。

## 10. 开源集成与许可

原则：依赖只选宽松许可（MIT/BSD/Apache-2.0）；GPL/AGPL 只做进程隔离或借鉴思路，不复制代码；非商用许可不碰。

| 项目 | 许可（已核） | 用法 |
|---|---|---|
| pyalex | MIT | OpenAlex 检索主干（英文/国际文献；中文期刊覆盖有限，约 GCJC 期刊 37%） |
| habanero | MIT（HTTPlib 依赖 httpx2，pydantic 维护） | Crossref DOI/卷期页补全 |
| arxiv / semanticscholar | MIT | 预印本与引用网络 |
| citeproc-py | BSD-2-Clause-Views | CSL 引用与参考文献渲染 |
| zotero-chinese/styles | CC BY-SA 3.0（样式文件，非代码） | 原样分发 GB/T 7714-2015 样式，NOTICE 署名 |
| python-bibtexparser | MIT | BibTeX 解析/生成 |
| rispy | MIT | RIS 解析 |
| pypdf | BSD-3 | PDF 文本与元数据（**不用 AGPL 的 PyMuPDF**） |
| jieba | MIT | 中文分词/词性，算实词密度与句长 |
| python-docx | MIT | DOCX 导出 |
| Vditor | MIT | 中文 Markdown 编辑器，静态资源随仓库分发 |
| FastAPI / uvicorn / Jinja2 / Pydantic / httpx | MIT / BSD-3 | 服务端与 HTTP |
| Zotero 7 本地 API | 客户端接口 | 只读同步；不打包、不修改 Zotero |
| Better BibTeX | MIT | 仅作为用户可选导出格式，不集成代码 |
| paper-qa | Apache-2.0 | 借鉴「检索—证据—引用」流水线与撤稿检查；不直接依赖（太重） |
| STORM | MIT | 借鉴多视角提问与大纲生成（已停更，不依赖） |
| local-deep-research | MIT | 借鉴本地模型编排与加密存储设计 |
| Humanizer-zh / academic-humanizer | MIT | 借鉴中文文风 lint 规则；不采用“过检测”话术 |
| gpt_academic | GPL-3.0 | 只借鉴交互，不复制代码 |
| ai-write-flow / cnki-aigc / aigc-reduce | MIT | 借鉴规则与三轮改写协议，自研实现 |
| blader/humanizer | MIT | 借鉴英文规则骨架，中文规则重写 |
| Gx664/AIGC | PolyForm-NC | 只读方法论，不复制、不商用 |
| skill-thesis-writer | MulanPSL-2.0 | 只参考章节结构；其 TTR 阈值与同义词策略明确不采用 |

**明确不用**：PyMuPDF（AGPL）、Zotero 本体嵌入（AGPL）、gpt_academic 代码（GPL）、AI-Scientist 系列（自定义许可+强制机器生成声明）、无 License 的 prompt 仓库（默认保留所有权利）、paper-search-mcp（内置可选 Sci-Hub 回退，红线）、Google Scholar 抓取库（ToS/CAPTCHA）。

**skills 集成**：仓库自带 `skills/`（literature-review、style-check、paragraph-edit、method-matrix、research-direction），既是本应用的提示词包，也能被 Claude/Codex 直接加载；全部自制，MIT。

**不做**：vendoring GPL 代码；打包知网客户端；集成灰色爬虫库。

## 11. 安全、隐私、学术诚信

- 只绑 127.0.0.1；校验 `Host` 与 `Origin`，防 DNS rebinding；token 存内存 + 页面注入。
- API key 存本地 SQLite（文件权限 600），支持 `WENSHU_LLM_API_KEY` 覆盖；UI 只显示尾四位。
- 零遥测、零外传；除用户主动检索/LLM 调用外不发请求。
- 导出 HTML 全转义；Markdown 渲染禁用原始 HTML。
- 文献元数据抓取只走公开 API，遵守 rate limit 与 mailto 礼貌池。
- 页面固定免责声明：风格体检不针对检测系统；AI 输出需作者负责；引用必须核。

## 12. Mac 适配清单

- `pyproject.toml` 要求 Python ≥3.11；提交 `uv.lock`；一条 `uv tool install`。
- CI 矩阵：macos-14 (arm64)、macos-13 (x86)、windows-latest、ubuntu-latest × Python 3.11/3.12。
- 路径用 `platformdirs`，不硬编码分隔符；中文文件名统一 NFC 并做长度保护。
- 数据目录、附件、导出全部支持中文与空格路径（测试覆盖）。
- FTS5 trigram 启动自检；不可用自动降级，不崩。
- 中文渲染：CSS 用 PingFang SC / Songti SC / Noto Sans CJK 回退；docx 指定宋体与 Times New Roman。
- 不依赖 Homebrew、Pandoc、LibreOffice、Java、Node；lxml 等扩展都有 arm64 wheel，不本地编译。
- 锁 Python 3.12（citeproc-py/lxml、arxiv、python-docx 兼容窗口最稳）。
- 提供 `scripts/install.command`（双击安装）与 `scripts/dev.sh`。
- 启动自动选端口、自动开浏览器、`--no-browser` 可关。
- 说明 Gatekeeper：终端安装不经公证，首次运行按提示允许即可。

## 13. 测试与验收

**自动化**
- 单测：16 条规则（黄金样本）、citeproc 渲染（GB/T 与 APA 黄金输出）、去重、diff、段落约束（±20%、引用保护）、DOCX 结构。
- API：TestClient + FakeLLM + respx 模拟检索源；覆盖导入/导出/核引/错误分支。
- 页面冒烟：所有路由 200，关键元素存在。
- CI 四平台跑通；`ruff` + `pytest`。

**人工验收（8 条，对应你的需求）**
1. 能在 Mac 上用一条命令装好并打开。
2. 能检索 OpenAlex/Crossref/S2/arXiv 并入库，能导入 RIS/BibTeX/PDF/Zotero。
3. 能对一个真实段落给出规则证据、风险分、安全修正与 diff。
4. 能润色一段并保持引用/术语/数字不变。
5. 能对一段做压缩/扩写/重排/补论证，输出理由与 gaps。
6. 能从本地库生成方法矩阵和年份趋势，并导出。
7. 能生成 3–5 个带证据边界的研究问题卡。
8. 能核验 DOI、导出 GB/T 参考文献与 DOCX，未核引有清单。

## 14. 里程碑

| 阶段 | 内容 | 产出 |
|---|---|---|
| M0 | 脚手架、配置、DB、FastAPI、页面壳、FakeLLM、CI | `wenshu` 能起 |
| M1 | 检索四源 + 文献库 + 导入 + PDF 全文 + Zotero | 真实文献能进能查 |
| M2 | 规则引擎 + 体检 UI + 安全修正 + LLM 改写 + 基线 | 段落能体检能改 |
| M3 | 润色 + 四类调段 + diff/回滚 | 段落能控 |
| M4 | 方法矩阵/趋势 + 研究方向 + 流程看板 | 研究面补齐 |
| M5 | 核引 + GB/T/APA + DOCX + 导出清单 | 能交付 |
| M6 | 文档、演示数据、截图、Mac 脚本、GitHub Actions、推送 | 开源可复现 |

## 15. 风险与未决

- 万方 `X-App-Key` 的接口字段与商用条款未核实 → 标「实验性」，失败不影响主流程。
- citeproc-py 的 GitHub 仓库对调研机返回 403，star 未核实；以 PyPI 0.12.1（BSD-2-Clause-Views）为准。
- GB/T 样式来自 CC BY-SA 3.0 的 `zotero-chinese/styles`：原样分发、NOTICE 署名；若改样式需同许可发布。
- Vditor 静态资源约 1MB；集成不顺就回退 textarea，不影响后端契约。
- 中文 NLP 不做重型模型：分词用 jieba，实体只做正则锚点；不吹 NER。
- LLM 输出不稳定 → 严格 JSON + 重试 + 规则降级 + 「未抽取」明示。
- 范围偏大 → P1 清单：页下脚注、GROBID、docling、Tauri 壳、向量检索、多用户。
- 你的论文材料不进仓库、不进演示；演示用虚构项目。

## 16. 需要你拍板

1. **形态**：本地单机（推荐）还是可部署多人？
2. **仓库**：`TheIslland/wenshu`，公开还是私有？名字要不要换？
3. **默认 LLM 预设**：DeepSeek（推荐）/ OpenAI / Ollama 本地 / 都放上但默认 DeepSeek？
4. **Codex**：要不要在动工前让 Codex 独立挑一遍架构刺（多花一点时间）？
