from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from backend.storage.db import db
from backend.models.competition_struct_model import CompetitionStruct


def _sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _norm_url(u: str) -> str:
    s = (u or "").strip()
    if not s or s == "无":
        return ""
    s = s.replace("https://http://", "http://").replace("http://https://", "https://")
    if "://" not in s and "." in s:
        s = "http://" + s
    # 业务口径：若抽到子站但主站存在于语料，优先主站（入库阶段先统一，避免后续查询混乱）
    if "aiic.china61.org.cn" in s:
        s = "http://www.china61.org.cn"
    return s.strip()


def _norm_reg_time(s: str) -> str:
    t = (s or "").strip()
    if not t or t == "无":
        return ""
    return t.replace("–", "-").replace("—", "-").strip()


def _infer_track_from_competition_id(cid: str) -> str:
    s = (cid or "").strip()
    if not s:
        return ""
    parts = s.split("_")
    # 去掉开头数字编号（如 01 / 07_1）
    while parts and parts[0].isdigit():
        parts.pop(0)
    if parts and parts[0].isdigit():
        parts.pop(0)
    t = "_".join(parts).strip()
    return t.replace("(1)", "").replace("（1）", "").strip()


def _split_main_and_track(name: str) -> tuple[str, str]:
    """
    兼容旧数据：以前会把“赛系+赛道”拼成一个字段（competition_name），这里尝试拆分回：
    - 主赛系
    - 赛名/赛道
    """
    n = (name or "").strip()
    if not n:
        return "", ""
    anchor = "第七届全国青少年人工智能创新挑战赛"
    if anchor in n and n != anchor:
        tail = n.split(anchor, 1)[1].strip()
        if tail:
            return anchor, tail
        return anchor, ""
    return n, ""


def upsert(
    *,
    dataset: str,
    competition_id: str,
    payload: dict[str, Any],
    source_text: str = "",
) -> CompetitionStruct:
    dataset = (dataset or "CompetitionDataset").strip()
    competition_id = (competition_id or "").strip()
    if not competition_id:
        raise ValueError("competition_id 不能为空")

    # === 新语义（单表长期可维护）===
    # competition_system: 赛系
    # competition_name: 赛名/赛道（单值；无则 "/"）
    competition_system = str(payload.get("competition_system") or "").strip()
    competition_name = str(payload.get("competition_name") or "").strip()

    # 兼容旧 payload：competition_name 里可能是“赛系+赛道”拼接；或通过 tracks 提供赛道
    tracks = payload.get("tracks")
    track_one = ""
    if isinstance(tracks, list) and tracks:
        track_one = str(tracks[0] or "").strip()
    if not competition_system:
        # 尝试从旧拼接里拆分
        main_name, tail_track = _split_main_and_track(competition_name)
        if main_name and tail_track:
            competition_system = main_name
            if not track_one:
                track_one = tail_track
    if not track_one:
        track_one = _infer_track_from_competition_id(competition_id)

    if not competition_system:
        # 最后兜底：把 competition_name 当赛系
        competition_system = competition_name
        competition_name = "/"

    # 如果 competition_name 还是空，则用 track_one（没有就 "/"）
    if not competition_name or competition_name == "无":
        competition_name = track_one or "/"
    if competition_name in ("无", "／", ""):
        competition_name = "/"

    organizer = str(payload.get("organizer") or "").strip()
    official_website = _norm_url(str(payload.get("official_website") or "").strip())
    registration_time = _norm_reg_time(str(payload.get("registration_time") or "").strip())
    competition_category = str(payload.get("competition_category") or "其他").strip() or "其他"
    session = str(payload.get("session") or "").strip()
    evidence_pages = str(payload.get("pdf_page") or payload.get("evidence_pages") or "").strip()
    raw_extract_json = json.dumps(payload, ensure_ascii=False)
    source_hash = _sha256_text(source_text) if source_text else ""

    row: Optional[CompetitionStruct] = CompetitionStruct.query.filter_by(
        dataset=dataset, competition_id=competition_id
    ).first()
    if not row:
        row = CompetitionStruct(dataset=dataset, competition_id=competition_id)
        db.session.add(row)

    row.competition_system = competition_system
    row.competition_name = competition_name
    row.organizer = organizer
    row.official_website = official_website
    row.registration_time = registration_time
    row.competition_category = competition_category
    row.session = session
    row.evidence_pages = evidence_pages
    row.raw_extract_json = raw_extract_json
    row.source_hash = source_hash

    db.session.commit()
    return row


def get_by_competition_id(dataset: str, competition_id: str) -> Optional[CompetitionStruct]:
    dataset = (dataset or "CompetitionDataset").strip()
    cid = (competition_id or "").strip()
    if not cid:
        return None
    return CompetitionStruct.query.filter_by(dataset=dataset, competition_id=cid).first()


def list_all(dataset: str) -> list[CompetitionStruct]:
    dataset = (dataset or "CompetitionDataset").strip()
    return (
        CompetitionStruct.query.filter_by(dataset=dataset)
        .order_by(CompetitionStruct.competition_id.asc())
        .all()
    )

