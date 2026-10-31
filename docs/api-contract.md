# API 契约（v0.1）

所有接口在 `/api` 下。除 `/api/health` 外，必须带 `X-Wenshu-Token`（页面会注入到
`<meta name="wenshu-token">`）。写操作还会校验 `Origin` 与 `Host`，只允许本机。

错误统一：

```json
{"error": {"code": "not_found", "message": "项目不存在。", "detail": null}}
```

## 约定

- ID 为整数；时间为 UTC ISO 8601 字符串。
- 分页暂不做，列表默认最多 200 条（检索可传 `limit`）。
- 文献 `authors` / `tags` 在 JSON 里是数组，DB 里是 JSON 文本。
- 文档保存用乐观锁：`PUT /api/documents/{id}` 必须带当前 `version`，冲突返回 409。

## 路由

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 版本、数据目录、LLM 配置、FTS、计数 |
| GET/POST | `/api/projects` | 列表 / 新建（自动建默认文档） |
| GET/PATCH/DELETE | `/api/projects/{id}` | 详情 / 改 / 删 |
| GET/POST | `/api/projects/{id}/documents` | 文档列表 / 新建 |
| GET | `/api/documents/{id}` | 文档详情（含正文） |
| PUT | `/api/documents/{id}` | 保存正文 `{content_md, version}` |
| DELETE | `/api/documents/{id}` | 删除 |
| GET | `/api/documents/{id}/outline` | 标题大纲 |
| POST/GET | `/api/documents/{id}/snapshots` | 建 / 列快照 |
| POST | `/api/documents/{id}/restore/{snapshot_id}` | 回滚 |
| POST | `/api/search` | `{query, sources[], year_from?, year_to?, language?, limit?}` |
| GET | `/api/search/history?project_id=` | 查询历史 |
| POST | `/api/search/doi` | `{doi}` 精确查 |
| GET | `/api/refs?project_id=&q=&status=&tag=` | 文献库 |
| POST | `/api/refs/import` | `{project_id, kind: doi/ris/bibtex/zotero, payload}` |
| POST | `/api/refs/{id}/attach` | multipart PDF |
| PATCH | `/api/refs/{id}` | 改元数据 / 标签 / 状态 |
| GET | `/api/refs/{id}/text?q=` | 全文片段 |
| GET | `/api/zotero/status` | 本地 API 是否可用 |
| POST | `/api/zotero/import` | `{project_id, limit?}` |
| POST | `/api/style/analyze` | `{text?, document_id?, project_id?, use_llm?}` |
| POST | `/api/style/fix` | 安全修正 |
| POST | `/api/style/rewrite` | 单条发现改写 |
| POST | `/api/style/baseline` | 个人基线 |
| POST | `/api/polish` | 润色 |
| POST | `/api/paragraphs/transform` | 调段 |
| POST | `/api/methods/extract` | 方法抽取 |
| GET | `/api/methods/matrix?project_id=` | 矩阵 + 趋势 |
| PATCH | `/api/methods/rows/{id}` | 改矩阵行 |
| POST | `/api/direction/explore` | 研究方向 |
| GET/POST/PATCH/DELETE | `/api/tasks` | 流程任务 |
| POST | `/api/workflow/template` | 套模板 |
| GET | `/api/workflow/gate?project_id=` | 导出前门禁 |
| POST | `/api/citations/verify` | 批量核引 |
| GET | `/api/citations/format?style=&ids=` | 格式化引用 |
| POST | `/api/export/{fmt}` | md/docx/bibtex/ris |
| GET/PUT | `/api/settings` | 设置（key 不回显） |
| POST | `/api/settings/test-llm` | 连接测试 |
