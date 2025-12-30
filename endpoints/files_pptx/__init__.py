from .summary_pptx import router as pptx_summary_router
from .analyze_pptx import router as pptx_analyze_router
from .qna_pptx import router as pptx_qna_router
from .translate_pptx import router as pptx_translate_router
from .rewrite_pptx import router as pptx_rewrite_router
from .compare_pptx import router as pptx_compare_router
from .deep_extract_pptx import router as pptx_deep_extract_router
from .grounded_search_pptx import router as pptx_grounded_search_router
from .structure_export_pptx import router as pptx_structure_export_router
from .extract_pptx import router as pptx_extract_router
from .classify_pptx import router as pptx_classify_router
from .multi_analyze_pptx import router as pptx_multi_analyze_router
from .ocr_extract_pptx import router as pptx_ocr_extract_router
from .layout_pptx import router as pptx_layout_router

__all__ = [
    "pptx_summary_router",
    "pptx_analyze_router",
    "pptx_qna_router",
    "pptx_translate_router",
    "pptx_rewrite_router",
    "pptx_compare_router",
    "pptx_deep_extract_router",
    "pptx_grounded_search_router",
    "pptx_structure_export_router",
    "pptx_extract_router",
    "pptx_classify_router",
    "pptx_multi_analyze_router",
    "pptx_ocr_extract_router",
    "pptx_layout_router",
]

