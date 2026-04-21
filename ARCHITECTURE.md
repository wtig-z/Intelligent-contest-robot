# ContestRobot_web 系统架构

## 一、整体概览

竞赛文档智能问答系统，基于 **Vidorag + GraphRAG 双引擎融合**架构。

```
用户提问
  ↓
Flask API → qa_service（双引擎路由）
  ↓                    ↓
ViDoRAG              GraphRAG
(视觉+文本检索)       (知识图谱检索)
  ↓                    ↓
动态答案融合 → 返回
```

核心技术栈：Flask / SQLAlchemy / ViDoRAG / Microsoft GraphRAG v3 / DashScope (Qwen)

## 二、项目结构

```
ContestRobot_web/
├── run.py                    # 启动入口
├── ingestion.py              # 嵌入生成：img→colqwen, unified_text→bge
├── requirements.txt          # Python 依赖
├── .env / .env.example       # 环境变量
│
├── config/                   # 配置层
│   ├── app_config.py         #   应用配置（模型名、缓存、历史轮数等）
│   ├── auth_config.py        #   认证配置（JWT、密码规则）
│   ├── logger_config.py      #   日志配置
│   └── paths.py              #   数据路径统一管理
│
├── backend/                  # 后端核心
│   ├── main.py               #   Flask 应用工厂 + 路由注册
│   ├── llm_chat.py           #   多轮→单轮总结、查询分类
│   ├── api/                  #   HTTP 接口层
│   │   ├── qa_api.py         #     POST /api/chat（问答）
│   │   ├── auth_api.py       #     登录/注册/Token
│   │   ├── history_api.py    #     问答历史
│   │   ├── profile_api.py    #     用户资料
│   │   ├── kb_api.py         #     知识库状态
│   │   ├── health_api.py     #     健康检查
│   │   └── admin_api/        #     管理后台 API
│   │       ├── pdf_manage_api.py
│   │       ├── user_manage_api.py
│   │       ├── vector_manage_api.py
│   │       ├── question_manage_api.py
│   │       └── graphrag_manage_api.py
│   ├── services/             #   业务服务层
│   │   ├── qa_service.py     #     双引擎融合问答（核心）
│   │   ├── oss_service.py    #     阿里云 OSS 图片上传
│   │   └── user_service.py   #     用户注册/登录
│   ├── models/               #   SQLAlchemy 数据模型
│   │   ├── user_model.py     #     User
│   │   ├── pdf_model.py      #     PDF
│   │   ├── question_model.py #     Question
│   │   └── vector_model.py   #     Vector
│   ├── storage/              #   数据库 CRUD 封装
│   ├── auth/                 #   JWT + 权限控制
│   ├── vidorag/              #   ViDoRAG 算法模块
│   │   ├── service.py        #     ViDoRAGService 对外接口
│   │   ├── search_engine.py  #     HybridSearchEngine（双路检索 + GMM + KMeans）
│   │   ├── agents.py         #     Seeker / Inspector / Synthesizer
│   │   ├── llms/             #     LLM 封装（Qwen-VL、BGE、ColQwen）
│   │   └── utils/            #     格式转换、图像处理
│   └── graphrag/             #   GraphRAG 模块
│       ├── __init__.py       #     导出 GraphRAGService
│       ├── service.py        #     索引构建 + 多级查询（basic/local/global/drift）
│       └── _lib/             #     vendored 微软 GraphRAG v3.0.6 完整源码
│           ├── graphrag/
│           ├── graphrag_storage/
│           ├── graphrag_llm/
│           └── ...（8 个包）
│
├── scripts/                  # 离线脚本
│   ├── update_knowledge.py   #   知识库增量更新（5 步管线）
│   ├── merge_ocr.py          #   双层 OCR 融合（ppocr + vlmocr → unified_text）
│   ├── build_graphrag.py     #   GraphRAG 索引构建（3 步）
│   ├── prepare_graphrag_input.py  # unified_text 页级→文档级
│   ├── ocr_triditional.py    #   PP-OCR 传统文字识别
│   ├── ocr_vlms.py           #   VLM OCR（qwen-vl-max）
│   ├── pdf2images.py         #   PDF → 页面图片
│   ├── migrate_db.py         #   数据库迁移
│   ├── init_db.py            #   数据库初始化 + 管理员账号
│   ├── batch_import_pdf.py   #   批量导入 PDF
│   └── export_questions.py   #   导出问答记录
│
├── frontend/                 # 前端
│   ├── index.html            #   主聊天页
│   ├── login/register.html   #   认证页
│   ├── history.html          #   问答历史
│   ├── profile.html          #   用户资料
│   ├── admin/                #   管理后台
│   └── static/               #   CSS + JS
│
└── data/CompetitionDataset/  # 数据集
    ├── pdf/                  #   原始 PDF（21 份）
    ├── img/                  #   页面图片（386 张）
    ├── ppocr/                #   PP-OCR 文本（386 页）
    ├── vlmocr/               #   VLM OCR JSON（386 页）
    ├── unified_text/         #   双层融合统一文本（386 页）
    ├── bge_ingestion/        #   BGE-m3 文本嵌入（386 节点）
    ├── colqwen_ingestion/    #   ColQwen2 视觉嵌入（386 节点）
    ├── kmeans_index/         #   K-Means 分层索引
    ├── graphrag/             #   GraphRAG 工作目录
    │   ├── settings.yaml     #     GraphRAG 配置
    │   ├── prompts/          #     提示词模板
    │   ├── input/            #     文档级文本（21 篇，来自 unified_text）
    │   └── output/           #     索引产物（构建后生成）
    └── archive/              #   历史归档
```

## 三、统一文本预处理架构

**所有文本数据来自同一条 OCR 管线，无 pdfminer 依赖。**

```
PDF 上传
  ↓
PDF → 页面图片 (pdf2image)
  ↓               ↓
PP-OCR → ppocr/   VLM OCR → vlmocr/
(传统文字识别)     (qwen-vl-max 结构化识别)
  ↓               ↓
     merge_ocr.py (双层融合)
  ↓
unified_text/{doc}_{page}.txt   ← 唯一标准文本
  ↓                              ↓
ViDoRAG                    GraphRAG
(bge_ingestion 文本嵌入)   (graphrag/input/ 文档级拼接)
```

**融合策略：**
- VLM OCR 为主干（保留表格/图表等结构化标注）
- PP-OCR 补全 VLM 可能遗漏的小字、页眉页脚
- `_load_page_text()` 三级回退：unified_text → vlmocr → bge_ingestion

## 四、知识库更新管线

`scripts/update_knowledge.py` — 5 步管线：

```
[1/5] PDF → 图片         pdf2image
[2/5] PaddleOCR          ocr_triditional.py → ppocr/
[3/5] VLM OCR            ocr_vlms.py → vlmocr/
[4/5] 双层 OCR 融合       merge_ocr.py → unified_text/
[5/5] 嵌入生成            ingestion.py → bge_ingestion/ + colqwen_ingestion/
```

GraphRAG 索引需单独构建：`python scripts/build_graphrag.py`

## 五、双引擎问答流程

`backend/services/qa_service.py` — 智能路由版：

```
用户消息 + 历史
  ↓
[阶段0] 多轮→单轮总结 (qwen-turbo)
  ↓
[阶段1] 查询类型分类 → basic/local/global (qwen-turbo)
  ↓
[阶段2] ViDoRAG 全流程检索
        HybridSearchEngine（ColQwen2 视觉 + BGE-m3 文本）
        → GMM 去噪 → 双路合并 → Seeker/Inspector/Synthesizer Agent
  ↓
[阶段3] GraphRAG 精准单级检索（按分类结果）
        basic_search / local_search / global_search
  ↓
[阶段4] 动态答案路由
        有视觉内容 + Vidorag 有答案 → Vidorag 为主，GraphRAG 补充
        GraphRAG 成功 → GraphRAG 为主
        其他 → Vidorag 回退
  ↓
[后处理] 图片上传 OSS、缓存、写入历史
```

## 六、GraphRAG 模块

**完全自包含，零外部依赖。**

- `backend/graphrag/_lib/`：vendored 微软 GraphRAG v3.0.6 全部源码（8 个包）
- 运行时通过 `sys.path.insert(0, _lib_dir)` 加载，等效于 pip install
- 索引构建和查询都通过 Python API 调用，不依赖 CLI 或外部 venv

**支持的检索模式：**
- `basic`：基于 text_units 的向量检索（最快最稳）
- `local`：实体+关系+社区的局部搜索
- `global`：社区报告的全局搜索
- `drift`：漂移搜索
- `auto`：basic → local 降级回退

**配置文件：** `data/<dataset>/graphrag/settings.yaml`

## 七、常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 初始化数据库
python scripts/init_db.py

# 启动服务
python run.py

# 知识库更新（含 OCR + 嵌入）
python scripts/update_knowledge.py --dataset CompetitionDataset

# 构建 GraphRAG 索引（含 OCR 融合 + 文本准备）
python scripts/build_graphrag.py

# 仅构建索引（已有 input 数据）
python scripts/build_graphrag.py --skip-prepare

# 数据库迁移
python scripts/migrate_db.py
```

## 八、环境变量

| 变量 | 用途 |
|------|------|
| `DASHSCOPE_API_KEY` | DashScope API 密钥（Qwen 系列模型） |
| `GRAPHRAG_API_KEY` | GraphRAG 用（通常与 DASHSCOPE 相同） |
| `VIDORAG_DATASET` | 默认数据集名 |
| `VIDORAG_LLM` | VLM 模型名（默认 qwen-vl-max） |
| `CHAT_LLM` | 文本 LLM（默认 qwen-turbo） |
| `JWT_SECRET_KEY` | JWT 签名密钥 |
| `OSS_*` | 阿里云 OSS 配置 |
