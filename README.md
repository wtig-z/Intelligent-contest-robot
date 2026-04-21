# Intelligent-contest-robot
竞赛智能客服机器人 | 大模型+RAG+知识图谱+ViDoRAG+MinerU 驱动的自动化问答服务

## 系统架构（简版）

```text
Intelligent-contest-robot
├── .env                         # 本地环境变量（已忽略，不上传）
├── .env.example                 # 环境变量模板
├── .gitignore
├── README.md
├── ARCHITECTURE.md              # 架构说明文档
├── run.py                       # 服务启动脚本
├── ingestion.py                 # 嵌入生成入口（img/text -> 向量节点）
├── requirements.txt             # Python 依赖清单
├── project_logger.py            # 日志配置
├── admin-event-management.html  # 管理页（根目录静态页）
├── event-calendar-center.html   # 日历页（根目录静态页）
├── testReadme.md                # 临时文档
├── text.py                      # 本地草稿文件（已忽略）
├── __pycache__/                 # Python 缓存（已忽略）
├── app/                         # Flask 应用装配与启动入口
├── backend/                     # 后端服务
│   ├── api/                     # HTTP 接口（问答、管理、历史）
│   ├── services/                # 业务服务（QA、OSS、火山知识库等）
│   ├── storage/                 # 数据访问层
│   ├── models/                  # 数据模型
│   ├── vidorag/                 # 检索/推理核心（ViDoRAG）
│   └── graphrag/                # GraphRAG 引擎与索引/查询能力
├── frontend/                    # 前端页面与交互逻辑
│   ├── *.html                   # 用户端/管理端页面
│   └── static/
│       ├── js/                  # 聊天、历史、管理台脚本
│       └── css/                 # 样式
├── config/                      # 路径与运行配置
├── scripts/                     # 知识库构建与维护脚本
│   ├── pdf2images.py            # PDF 转图片
│   ├── ocr_vlms.py              # VLM OCR
│   ├── build_graphrag.py        # 构建 GraphRAG 图索引
│   └── update_knowledge.py      # 一键更新知识库
├── data/                        # 数据集与中间产物（已忽略）
│   └── <dataset>/
│       ├── img/                 # 页面图片
│       ├── ppocr/               # OCR 文本
│       ├── vlmocr/              # VLM OCR 结构化结果
│       ├── unified_text/        # 融合文本
│       ├── bge_ingestion/       # 文本向量节点
│       ├── colqwen_ingestion/   # 视觉向量节点
│       └── graphrag/            # GraphRAG 输入/索引/缓存产物
├── doc/                         # 项目文档
├── qa_evaluation/               # 问答评测模块
├── paper_evaluation/            # 论文/数据评测模块
├── logs/                        # 运行日志（已忽略）
└── scripts/                     # 构建与运维脚本
    ├── pdf2images.py
    ├── ocr_vlms.py
    ├── build_graphrag.py
    └── update_knowledge.py
```

