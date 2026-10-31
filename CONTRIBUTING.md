# Contributing

Thanks for helping 文枢 Wenshu. This is a local-first tool for humanities researchers; correctness and citation integrity matter more than feature count.

## 开发环境

```bash
git clone https://github.com/TheIslland/wenshu.git
cd wenshu
uv sync --all-extras
uv run wenshu --demo --no-browser
```

要求 Python 3.12（`requires-python >=3.11,<3.14`），uv 管理依赖；不要引入需要本地编译的包。

## 提交前

```bash
git config user.email "you@example.com"   # 或 username@users.noreply.github.com
uv run python scripts/check_identity.py
uv run ruff check .
uv run pytest -q
```

**不要把密码、用户名、手机号填进 `git config user.email`**：公开仓库的提交元数据会永久暴露它。CI 会检查 author/committer 邮箱是否像邮箱。

CI 跑 Linux / macOS / Windows。测试不能访问公网：检索用 `respx`，LLM 用 `FakeLLM`。

## 代码约定

- 后端同步函数即可（FastAPI 会放线程池）；不要在请求里开长连接。
- 数据库用 `sqlite3.Row` + 显式 SQL；新表/列先改 `db.py` 并说明迁移。
- 服务层函数把 `sqlite3.Connection` 作为第一个参数，便于事务与测试。
- 用户可见错误抛 `AppError` 子类，统一 `{error:{code,message,detail}}`；不要 500 裸奔。
- 前端无构建链：Jinja2 + 原生 JS module/IIFE；不要引 CDN、外链字体、需要编译的框架。
- 中文文本 UTF-8 + NFC；附件按 `sha256[:16].pdf`；不要用标题做文件名。

## 不许做的事

- 复制 GPL/AGPL/无 License/非商用许可的代码。
- 加入知网/维普/Google Scholar 爬虫、Sci-Hub 回退、检测规避话术。
- 生成或补全本地库/检索结果之外的文献、DOI、页码。
- 把 API key、用户数据、论文全文写进日志或提交。

## 分支与提交

- 一个 PR 一件事；提交信息用 `feat:` / `fix:` / `docs:` / `test:` / `chore:`。
- 改行为必须带测试；改 UI 至少保证路由 200 与关键 DOM 标记存在。
- 不要提交 `data/`、`*.db`、`.venv/`、导出文件。

## 报告问题

请附：系统与 Python 版本、启动命令、复现步骤、终端报错、`/api/health` 输出（去掉 key）。安全问题请私下联系维护者，不要开公开 issue。
