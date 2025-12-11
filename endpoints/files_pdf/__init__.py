from .analyze_pdf import router as pdf_analyze_router
from .summary_pdf import router as pdf_summary_router
from .qna_pdf import router as pdf_qna_router
from .extract_pdf import router as pdf_extract_router
from .compare_pdf import router as pdf_compare_router
from .rewrite_pdf import router as pdf_rewrite_router
from .classify_pdf import router as pdf_classify_router
from .multianalyze_pdf import router as pdf_multianalyze_router
from .ocr_extract_pdf import router as pdf_ocr_extract_router
from .layout_pdf import router as pdf_layout_router
from .deepextract_pdf import router as pdf_deepextract_router
from .grounded_search_pdf import router as pdf_grounded_search_router
from .translate_pdf import router as pdf_translate_router
from .structure_export_pdf import router as pdf_structure_export_router

__all__ = [
    "pdf_analyze_router",
    "pdf_summary_router",
    "pdf_qna_router",
    "pdf_extract_router",
    "pdf_compare_router",
    "pdf_rewrite_router",
    "pdf_classify_router",
    "pdf_multianalyze_router",
    "pdf_ocr_extract_router",
    "pdf_layout_router",
    "pdf_deepextract_router",
    "pdf_grounded_search_router",
    "pdf_translate_router",
    "pdf_structure_export_router",
]

