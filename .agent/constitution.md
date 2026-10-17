# AgentForge WeChat Shop Constitution

1. Agent 不得直接写 `main`。
2. 业务变更必须关联 REQ 与 TASK。
3. Agent 不得通过修改需求来迎合实现。
4. 不得猜测 API、数据库字段、认证方式、支付规则或权限规则。
5. Backend 获取当前用户必须复用 `CurrentUser`；禁止自行发明 `X-User-Id` 等认证头。
6. 新增生产依赖必须有架构依据；核心依赖变化必须创建 ADR。
7. 微信支付使用 API v3 官方 Java SDK，回调必须验签并实现幂等。
8. 数据库结构变化必须通过 Flyway migration。
9. 测试/CI 未通过，不得宣告任务完成。
10. 长期 Memory 只允许基于已合并事实写入。
11. 遇到关键未知信息必须 BLOCK，不得用“行业常见做法”替代项目事实。
