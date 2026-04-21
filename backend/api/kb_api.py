"""知识库状态接口"""
import os
from flask import Blueprint, jsonify

from config.app_config import DEFAULT_DATASET
from config.paths import (
    get_pdf_dir,
    get_unified_text_dir,
    get_graphrag_dir,
    get_bge_ingestion_dir,
)
from backend.storage import pdf_storage, question_storage, vector_storage

bp = Blueprint('kb', __name__, url_prefix='/api/kb')


@bp.route('/status', methods=['GET'])
def status():
    """知识库状态（真实统计）"""
    pdf_dir = get_pdf_dir(DEFAULT_DATASET)
    unified_dir = get_unified_text_dir(DEFAULT_DATASET)
    graphrag_dir = get_graphrag_dir(DEFAULT_DATASET)
    bge_dir = get_bge_ingestion_dir(DEFAULT_DATASET)

    db_pdf_count = len(pdf_storage.list_all(DEFAULT_DATASET))
    file_pdf_count = len([f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')]) if os.path.isdir(pdf_dir) else 0
    unified_pages = len([f for f in os.listdir(unified_dir) if f.lower().endswith('.txt')]) if os.path.isdir(unified_dir) else 0
    bge_nodes = len([f for f in os.listdir(bge_dir) if f.lower().endswith('.node')]) if os.path.isdir(bge_dir) else 0
    question_total = question_storage.count_all()
    vector_total = len(vector_storage.list_all())
    graphrag_ready = os.path.isdir(os.path.join(graphrag_dir, 'output'))

    return jsonify({
        'status': 'ok',
        'message': 'ok',
        'data': {
            'dataset': DEFAULT_DATASET,
            'pdf_count': db_pdf_count,
            'pdf_file_count': file_pdf_count,
            'unified_text_pages': unified_pages,
            'bge_node_count': bge_nodes,
            'question_total': question_total,
            'vector_total': vector_total,
            'graphrag_output_ready': graphrag_ready,
        }
    })
