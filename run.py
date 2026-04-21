#!/usr/bin/env python3
"""启动入口"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# 必须在任何 import torch / backend 之前设置，否则 GPU 掩码不生效
# 物理 GPU 编号 0/1/2：使用第 3 张卡时设为 2；掩码后进程内仅见 cuda:0
_cuda = (os.getenv("CUDA_VISIBLE_DEVICES", "2") or "2").strip()
if _cuda:
    os.environ["CUDA_VISIBLE_DEVICES"] = _cuda
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# 项目根目录加入 path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.main import app

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
