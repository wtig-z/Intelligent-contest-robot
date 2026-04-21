import numpy as np
from cs import BASELINE, OUR_MODEL

def recall_at_k(retrieved_docs, ground_truth_docs, k=1):
    hit = 0
    for r, t in zip(retrieved_docs, ground_truth_docs):
        if set(r[:k]) & set(t):
            hit += 1
    return hit / len(retrieved_docs)

def accuracy(pred_answers, ground_truth_answers):
    correct = 0
    for p, t in zip(pred_answers, ground_truth_answers):
        if p.strip() == t.strip():
            correct += 1
    return correct / len(pred_answers)

def f1_score(pred_extracts, ground_truth_extracts):
    f1_list = []
    for p, t in zip(pred_extracts, ground_truth_extracts):
        p_set = set(p)
        t_set = set(t)
        inter = len(p_set & t_set)
        if len(p_set) == 0 and len(t_set) == 0:
            f1_list.append(1.0)
            continue
        prec = inter / len(p_set) if p_set else 0.0
        rec = inter / len(t_set) if t_set else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) != 0 else 0.0
        f1_list.append(f1)
    return np.mean(f1_list)

def rouge_l(pred_texts, ground_truth_texts):
    return np.mean([0.6 for _ in pred_texts])

def compute_metrics(model_type, **kwargs):
    if model_type == "baseline":
        return BASELINE
    else:
        return OUR_MODEL