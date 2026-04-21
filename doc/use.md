
## 快速开始

1. 安装依赖：`pip install -r requirements.txt`
2. 配置环境变量：复制 `.env.example` 为 `.env`，填入 `DASHSCOPE_API_KEY`
3. 准备数据：将竞赛 PDF 放入 `data/CompetitionDataset/pdf/`
4. 构建知识库：`python scripts/pdf2images.py`，`python scripts/ocr_vlms.py`，`python ingestion.py`
5. 启动：`python run.py`

## API

- `POST /api/chat`  body: `{"message": "问题"}`  → 返回 `{answer, images, rewritten}`

#wt专用
http://127.0.0.1:5000/volc-kb
conda activate watercomment
cp .env.example .env
编辑env里的key

 python run.py


 新的

 conda activate contestrobot_py312
  export PYTHONNOUSERSITE=1
 export HF_OFFLINE=1
cd /data/zwt/test/AG/ContestRobot_web
python scripts/build_graphrag.py --skip-prepare
python run.py


评测的
python /data/zwt/test/AG/ContestRobot_web/qa_evaluation/main.py --data_path /data/zwt/test/AG/ContestRobot_web/qa_evaluation/mo/dataset.json


 把“人工加对齐的数据”像 prompts.py 一样独立成脚本（便于后续追加）
我已经给你做成了“数据文件 + 生成脚本”的维护方式，后续加 PDF 只要追加一行数据再跑脚本即可：

结构化知识库源文件（TSV）：data/curated_competitions.tsv
你以后新增赛事/赛道，直接往这个 TSV 里追加行（包含 id 列）。
生成脚本：scripts/build_curated_structured.py
它会把 TSV/CSV 转成 config/curated_structured.py（系统实际读取的 Python 列表）。
运行方式：

/data/miniconda/envs/contestrobot_py312/bin/python scripts/build_curated_structured.py \
  --input data/curated_competitions.tsv \
  --output config/curated_structured.py
跑完刷新服务/重启即可生效。


后台进入「文档管理」
点 「仅重建结构化表」
看下方实时输出完成后，你的 SQLite competition_structs 就会按 TSV 对齐了（不需要重启服务）






(contestrobot_py312) aiiiin@ai:/data/zwt/test/AG/ContestRobot_web$ ss -ltnp | grep ':5000'
LISTEN 0      128          0.0.0.0:5000       0.0.0.0:*    users:(("python",pid=1443011,fd=59))       
(contestrobot_py312) aiiiin@ai:/data/zwt/test/AG/ContestRobot_web$ kill 1443011