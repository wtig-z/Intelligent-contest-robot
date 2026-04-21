 介绍：
 竞赛文档RAG问答
 有几个只是答辩的时候展示的包括测试的那些脚本，还有buid向量库的那几个脚本

 数据库用的是sqlite可以直接在data文件夹看
 跑的是2号显卡

 
 
 启动：
 有两个pipeline第一个是火山api的下面的命令启动的就是火山api的

 conda activate contestrobot_py312
  export PYTHONNOUSERSITE=1
 export HF_OFFLINE=1
cd /data/zwt/test/AG/ContestRobot_web
python scripts/build_graphrag.py --skip-prepare
python run.py


如果要启动graph和cidorag那个pipeline要改一下启动文件run.py


跑火山那个pipeline要配
DEFAULT_DOMAIN = "api-knowledgebase.mlp.cn-beijing.volces.com"
DEFAULT_PROJECT = "default"
DEFAULT_COLLECTION = "wt"
DEFAULT_MODEL = "Doubao-seed-1-8"
DEFAULT_MODEL_VERSION = "251228"

VOLC_KB_AK（Access Key ID）
VOLC_KB_SK（AccessKey Secret）
VOLC_KB_ACCOUNT_ID账号ID
 不管哪个方案都要用千问的key
 生成模型用的是千问api
 对于一些嵌入模型和ocr等模型是下载到本地了，当然没传到仓库。
 用户上传的图是传到OSS的也要配

 # 阿里云 OSS（图片上传）
OSS_ACCESS_KEY_ID
OSS_ACCESS_KEY_SECRET
OSS_REGION
OSS_BUCKET_NAME
OSS_PATH
OSS_ENDPOINTm
OSS_USE_CNAME=

# Auth / DB
# SQLite 建议使用相对路径（项目可迁移、部署到别处不受影响）
# 程序会按“项目根目录”解析该相对路径并自动创建目录
DATABASE_URL=sqlite:///data/contest_robot.db
JWT_SECRET_KEY=change-me-in-production
JWT_ACCESS_TOKEN_EXPIRES=3600
JWT_REFRESH_TOKEN_EXPIRES=604800
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123


使用：

管理员admin 密码admin123
用户zwt密码zwt123

至于文档上传与更新与向量化和图谱构建等好像后台那个一键能执行


代码：
qa_evaluation这个文件夹不用看写论文用的
paper_evaluation同理
日志在logs
当天的除外日志会在logs的archive文件夹下归档
data文件夹下就是包括数据库sqlite和源pdf以及知识图谱的社区等还有vidorag用的节点向量文件
_vector_db这个不用看，写论文用的
VIDORAG和GRAPHRAG就是在backend文件夹里各自作为一个算法包在架构里
MinerU实际上在这里没用到，主要写论文用的
火山的就几个脚本很好区分一般是volc_kb_chat有v和k的