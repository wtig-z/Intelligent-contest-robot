"""
项目配置包：运行时参数、路径、日志、以及「可提交」的赛事数据快照。

- golden_kb：人工 Golden 结构化知识库（问答优先数据源之一）
- curated_competitions：由 TSV 生成的赛事表
- curated_structured：人工对齐的结构化赛事列表
- qa_intent_keywords：全量召回与视觉问句兜底关键词
- qa_route_policy：结构化知识库捷径 vs RAG 的路由策略（与 qa_intent_keywords 职责分离）
- curated_fusion_prompt：结构化知识库 + RAG 融合用 system 提示词（与 vidorag.agent.prompts 共用）
其余模块见各文件 docstring。
"""
