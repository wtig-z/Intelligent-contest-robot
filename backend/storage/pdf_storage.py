"""PDF CRUD"""
from backend.storage.db import db
from backend.models.pdf_model import PDF


def list_all(dataset: str = None):
    q = PDF.query
    if dataset:
        q = q.filter_by(dataset=dataset)
    return q.order_by(PDF.created_at.desc()).all()


def get_by_id(pdf_id: int) -> PDF:
    return PDF.query.get(pdf_id)


def create(filename: str, file_path: str, dataset: str = "CompetitionDataset",
           file_hash: str = None, contest_name: str = None) -> PDF:
    if not contest_name:
        contest_name = filename[:-4] if filename.lower().endswith('.pdf') else filename
    p = PDF(filename=filename, contest_name=contest_name,
            file_path=file_path, dataset=dataset, file_hash=file_hash)
    db.session.add(p)
    db.session.commit()
    return p


def update_contest_name(pdf_id: int, contest_name: str):
    """管理员修改赛事名称"""
    p = PDF.query.get(pdf_id)
    if p:
        p.contest_name = contest_name
        db.session.commit()
    return p


def get_by_filename(dataset: str, filename: str) -> PDF:
    """按数据集与文件名查一条记录。"""
    return PDF.query.filter_by(dataset=dataset, filename=filename).first()


def update_file_hash(pdf_id: int, file_hash: str):
    p = PDF.query.get(pdf_id)
    if p:
        p.file_hash = file_hash
        db.session.commit()
    return p


def update_status(pdf_id: int, status: str):
    p = PDF.query.get(pdf_id)
    if p:
        p.status = status
        db.session.commit()
    return p


def delete_by_id(pdf_id: int):
    """删除一条 PDF 记录（用于知识库同步时「已从磁盘删除」的条目）。"""
    p = PDF.query.get(pdf_id)
    if p:
        db.session.delete(p)
        db.session.commit()
        return True
    return False
