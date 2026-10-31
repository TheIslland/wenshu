# Security Policy

文枢 Wenshu runs locally and stores research data on the user's machine. We take
credential leaks, citation fabrication and local-network exposure seriously.

## 报告问题

请**不要**开公开 issue。通过 GitHub 仓库维护者页面联系 TheIslland，或发私信，
附：影响版本、复现步骤、是否需要联网、是否涉及数据外传。我们会在 72 小时内回复。

## 本地安全模型

- 服务只监听 `127.0.0.1`，启动时生成一次性 token；页面与 API 都带 token。
- API 还校验 `Host` 与 `Origin`，拒绝跨站写请求。
- LLM key 存本地 SQLite（数据目录权限 700），不写日志、不上传；可用环境变量覆盖。
- 零遥测。除用户主动触发的检索/LLM 调用外不发网络请求。
- 检索只走官方 API；不内置知网/维普/Google Scholar 爬虫、不使用 Sci-Hub。

## 已知边界

- 本机其他进程可以读数据目录（取决于操作系统账户权限）；不要在共享账户上跑敏感项目。
- 导出 docx 后由 Word/其他编辑器接管，其宏与外部链接不在本工具控制范围内。
- LLM 输出不可信；所有文献线索必须核验，工具不会替你保证真实性。

## 供应链

依赖只选 MIT/BSD/Apache-2.0/BlueOak；CSL 样式为 CC BY-SA 3.0 并单独署名。
`uv.lock` 固定版本；CI 在 Linux/macOS/Windows 上跑测试。

## 提交防线

- `scripts/check_sensitive.py --staged` 是 pre-commit 钩子，扫描 key/token/私钥/密码赋值；`--all` 用于 CI 全仓审计。
- `scripts/check_identity.py` 拒绝不含 `@` 的 commit 邮箱，防止把密码/用户名写进 `user.email`。
- 安装钩子：`uv run python scripts/install_hooks.py`。
- 发现泄露时：先轮换凭据，再改代码/历史，再强推；通知维护者，不要只删文件。
