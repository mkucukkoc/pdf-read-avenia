from .summary_word import router as word_summary_router
from .analyze_word import router as word_analyze_router
from .qna_word import router as word_qna_router
from .translate_word import router as word_translate_router
from .rewrite_word import router as word_rewrite_router
from .compare_word import router as word_compare_router
from .extract_word import router as word_extract_router
from .classify_word import router as word_classify_router
from .multi_analyze_word import router as word_multi_analyze_router
from .ocr_extract_word import router as word_ocr_extract_router
from .layout_word import router as word_layout_router
from .deep_extract_word import router as word_deep_extract_router
from .grounded_search_word import router as word_grounded_search_router
from .structure_export_word import router as word_structure_export_router

__all__ = [
    "word_summary_router",
    "word_analyze_router",
    "word_qna_router",
    "word_translate_router",
    "word_rewrite_router",
    "word_compare_router",
    "word_extract_router",
    "word_classify_router",
    "word_multi_analyze_router",
    "word_ocr_extract_router",
    "word_layout_router",
    "word_deep_extract_router",
    "word_grounded_search_router",
    "word_structure_export_router",
]

