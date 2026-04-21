"""向量 CRUD"""
from backend.storage.db import db
from backend.models.vector_model import Vector


def list_all(vector_type: str = None):
    q = Vector.query
    if vector_type:
        q = q.filter_by(vector_type=vector_type)
    return q.order_by(Vector.created_at.desc()).all()


def get_by_id(vec_id: int) -> Vector:
    return Vector.query.get(vec_id)
