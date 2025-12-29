from __future__ import annotations

from typing import Dict, List

from .config import PAYLOAD_BUILDERS

# Each case references a payload builder key in PAYLOAD_BUILDERS
TEST_CASES: List[Dict] = [
    {"name": "pdf_analyze", "method": "POST", "path": "/api/v1/files/pdf/analyze", "payload": "analyze"},
    {"name": "pdf_summary", "method": "POST", "path": "/api/v1/files/pdf/summary", "payload": "summary"},
    {"name": "pdf_qna", "method": "POST", "path": "/api/v1/files/pdf/qna", "payload": "qna"},
    {"name": "pdf_extract", "method": "POST", "path": "/api/v1/files/pdf/extract", "payload": "extract"},
    {"name": "pdf_compare", "method": "POST", "path": "/api/v1/files/pdf/compare", "payload": "compare"},
    {"name": "pdf_rewrite", "method": "POST", "path": "/api/v1/files/pdf/rewrite", "payload": "rewrite"},
    {"name": "pdf_classify", "method": "POST", "path": "/api/v1/files/pdf/classify", "payload": "classify"},
    {"name": "pdf_multianalyze", "method": "POST", "path": "/api/v1/files/pdf/multianalyze", "payload": "multianalyze"},
    {"name": "pdf_ocr_extract", "method": "POST", "path": "/api/v1/files/pdf/ocr_extract", "payload": "ocr_extract"},
    {"name": "pdf_layout", "method": "POST", "path": "/api/v1/files/pdf/layout", "payload": "layout"},
    {"name": "pdf_deepextract", "method": "POST", "path": "/api/v1/files/pdf/deepextract", "payload": "deepextract"},
    {"name": "pdf_grounded_search", "method": "POST", "path": "/api/v1/files/pdf/grounded_search", "payload": "grounded_search"},
    {"name": "pdf_translate", "method": "POST", "path": "/api/v1/files/pdf/translate", "payload": "translate"},
    {"name": "pdf_structure_export", "method": "POST", "path": "/api/v1/files/pdf/structure_export", "payload": "structure_export"},
]


def get_payload(name: str):
    builder = PAYLOAD_BUILDERS.get(name)
    if not builder:
        raise ValueError(f"Payload builder not found for key: {name}")
    return builder()







