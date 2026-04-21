import json
import random
import os

# 基础题库（竞赛机器人相关，贴合毕设主题）
BASE_QUESTIONS = [
    "第七届全国青少年人工智能创新挑战赛对机器人尺寸有什么要求？",
    "比赛现场提供什么类型的电源接口？",
    "小学低年级组的机器人是否可以使用无线遥控？",
    "机器人的重量限制是多少千克？",
    "比赛允许使用的传感器类型有哪些？",
    "机器人的运行时间限制是多少分钟？",
    "参赛队伍的人数上限是多少？",
    "比赛的评分标准包含哪些维度？",
    "机器人的控制方式有哪些限制？",
    "比赛场地的尺寸是多少米？",
    "机器人的电池电压限制是多少伏？",
    "是否允许使用预训练的AI模型辅助控制？",
    "比赛的初赛和复赛规则有什么不同？",
    "机器人的外观设计是否有评分项？",
    "参赛作品的提交截止时间是什么时候？"
]

BASE_ANSWERS = [
    "机器人在出发区内的最大尺寸为{w}cm×{h}cm×{d}cm",
    "比赛现场提供当地标准{type}电源接口，参赛队需自行准备转换器",
    "{grade}组的机器人可使用{control}遥控",
    "机器人的重量限制为{weight}千克（含电池）",
    "允许使用{sensor}传感器，禁止使用{forbid_sensor}传感器",
    "机器人的单次运行时间限制为{time}分钟，超时将扣分",
    "每支参赛队伍的人数上限为{num}人，包含指导老师1名",
    "评分标准包含{dim1}、{dim2}、{dim3}三个核心维度",
    "仅允许使用{control_type}控制方式，禁止使用{forbid_control}方式",
    "比赛场地的尺寸为{len}米×{wid}米，高度限制{h}米",
    "机器人的电池电压不得超过{volt}伏，避免安全隐患",
    "{allow}使用预训练AI模型，需提前报备模型名称和版本",
    "初赛侧重{round1}，复赛侧重{round2}，决赛增加{round3}环节",
    "外观设计占总分的{score}%，主要考察{factor1}和{factor2}",
    "参赛作品提交截止时间为{year}年{month}月{day}日{hour}点"
]

# 填充参数池（保证数据多样性）
PARAMS = {
    "w": [20, 25, 30, 35],
    "h": [20, 25, 30, 35],
    "d": [20, 25, 30, 35],
    "type": ["220V交流", "110V交流", "USB-C直流"],
    "grade": ["小学低年级", "小学高年级", "初中", "高中"],
    "control": ["无线", "有线", "蓝牙", "红外"],
    "weight": [1, 2, 3, 4, 5],
    "sensor": ["视觉", "超声波", "红外", "触觉"],
    "forbid_sensor": ["激光", "微波", "压力"],
    "time": [3, 5, 8, 10],
    "num": [2, 3, 4, 5],
    "dim1": ["功能完成度", "运行稳定性", "创新设计"],
    "dim2": ["能耗效率", "响应速度", "操作便捷性"],
    "dim3": ["故障恢复能力", "环境适应性", "成本控制"],
    "control_type": ["蓝牙", "WiFi", "有线"],
    "forbid_control": ["红外", "声波", "远程网络"],
    "len": [2, 3, 4, 5],
    "wid": [2, 3, 4, 5],
    "volt": [6, 9, 12, 15],
    "allow": ["允许", "禁止", "有条件允许"],
    "round1": ["功能验证", "基础操作", "稳定性测试"],
    "round2": ["复杂任务", "对抗性测试", "多场景适配"],
    "round3": ["现场答辩", "方案讲解", "技术创新点评"],
    "score": [5, 10, 15, 20],
    "factor1": ["美观性", "实用性", "轻量化"],
    "factor2": ["模块化设计", "易维护性", "环保材料"],
    "year": [2024, 2025, 2026],
    "month": [4, 5, 6, 7],
    "day": [10, 15, 20, 25],
    "hour": [12, 14, 16, 18]
}

def generate_fake_answer(template):
    """填充答案模板，生成多样化答案"""
    for key, values in PARAMS.items():
        if f"{{{key}}}" in template:
            template = template.replace(f"{{{key}}}", str(random.choice(values)))
    return template

def generate_test_data(num_samples=400):
    """生成指定数量的测试数据"""
    test_data = []
    for i in range(num_samples):
        # 随机选择问题和答案模板
        question = random.choice(BASE_QUESTIONS)
        answer_template = random.choice(BASE_ANSWERS)
        ground_truth_answer = generate_fake_answer(answer_template)
        
        # 生成检索文档ID（模拟真实文档库）
        doc_num = random.randint(1, 1000)
        ground_truth_docs = [f"doc_{doc_num}", f"doc_{doc_num+1}"] if random.random() > 0.5 else [f"doc_{doc_num}"]
        
        # 生成关键信息抽取结果（拆分答案关键词）
        ground_truth_extracts = [word for word in ground_truth_answer.split() if len(word) > 2][:3]
        
        # 组装单条数据
        sample = {
            "question": question,
            "ground_truth_answer": ground_truth_answer,
            "ground_truth_docs": ground_truth_docs,
            "ground_truth_extracts": ground_truth_extracts
        }
        test_data.append(sample)
    
    return test_data

if __name__ == "__main__":
    # 创建data目录
    os.makedirs("./data", exist_ok=True)
    # 生成400条数据
    test_data = generate_test_data(num_samples=400)
    # 写入JSON文件
    with open("./data/test_dataset.json", "w", encoding="utf-8") as f:
        json.dump(test_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 成功生成400条测试数据，保存至 ./data/test_dataset.json")