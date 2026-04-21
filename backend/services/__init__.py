"""
业务服务层：问答编排、结构化知识库查询、文档流水线、对象存储、任务注册等。

- `qa_service`：主入口（由 `qa_api` 调用）。
- `curated_database_query`：Golden/TSV 确定性路由（`config.golden_kb`）。
- `qa_curated_helpers`：结构化知识库检索与 RAG 融合用的上下文拼装。
"""
