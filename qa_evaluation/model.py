import json
import os
import time
import random

def load_test_dataset(data_path):
    time.sleep(random.uniform(0.05, 0.18))

    if not os.path.exists(data_path):
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        dummy = [
            {"question":"q","ground_truth_answer":"a","ground_truth_docs":["d"],"ground_truth_extracts":["k"]}
        ]
        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(dummy, f)

    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    questions = [d["question"] for d in data]
    gt_ans = [d["ground_truth_answer"] for d in data]
    gt_docs = [d["ground_truth_docs"] for d in data]
    gt_ext = [d["ground_truth_extracts"] for d in data]

    print(f"[INFO] 数据集加载完成，共{len(questions)}条样本")
    return questions, gt_ans, gt_docs, gt_ext