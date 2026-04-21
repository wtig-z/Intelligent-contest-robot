import json
import os

def load_test_dataset(data_path):
    """加载问答任务测试数据集"""
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"测试数据集路径不存在: {data_path}")
    
    with open(data_path, 'r', encoding='utf-8') as f:
        test_data = json.load(f)
    
    # 拆分问题、真实答案、真实依据文档
    questions = [item['question'] for item in test_data]
    ground_truth_answers = [item['ground_truth_answer'] for item in test_data]
    ground_truth_docs = [item['ground_truth_docs'] for item in test_data]
    ground_truth_extracts = [item['ground_truth_extracts'] for item in test_data]
    
    return questions, ground_truth_answers, ground_truth_docs, ground_truth_extracts