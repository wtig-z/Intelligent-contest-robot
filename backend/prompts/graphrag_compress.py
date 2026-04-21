"""GraphRAG 原始回答 → 二次 LLM 精简（智能竞赛客服机器人口径）。"""


def build_graphrag_compress_user_message(user_query: str, raw_answer: str) -> str:
    """
    与 GraphRAG 侧占位符无关：整段作为单次 User 消息，避免 raw_answer 中含花括号时被 format 误解析。
    """
    q = (user_query or "").strip()
    ctx = (raw_answer or "").strip()
    return (
        "你是智能竞赛客服机器人，回答简洁、口语化、分点、不啰嗦。\n"
        "不写学术内容，不堆砌术语，不长篇大论。\n"
        "控制长度在 600 字以内。\n"
        "重要：仅依据下方「资料」归纳；不得为凑数编造资料中未出现的赛事名称。\n"
        "若用户问「数学建模类」与「数据挖掘类」请区分：不要把泰迪杯、电赛、三创赛等与数学建模主赛道混为一谈，除非资料里同时写明。\n"
        "列举数学建模核心赛时，不要自创赛事名；不要输出 CUMCM、NCMMMC、NCSMMC 等英文缩写代称，用中文通用简称（如高教社杯、深圳杯、华为杯）。\n"
        f"用户问题：{q}\n"
        f"资料：{ctx}"
    )
