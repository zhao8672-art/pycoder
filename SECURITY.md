# 安全与密钥管理

本项目不应包含任何真实的 API Key 或敏感凭据。请遵守以下规则：

- 不要在仓库中提交 `.env` 或 `config.json` 带有实际密钥的文件。
- 使用 `.env.example` 与 `config.example.json` 提供示例模板。
- 在 CI 中使用 GitHub Secrets 注入真实凭据；永远不要把 secrets 写入日志或 artifact。
- 若怀疑泄露，请立刻旋转相应密钥并检查 git 历史（`git log --all -S 'sk-'`）。

推荐使用工具：`git-secrets`、`truffleHog` 进行仓库扫描。可在 CI 中配置定期审计。
