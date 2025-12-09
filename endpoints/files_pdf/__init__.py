from .analyze_pdf import router as pdf_analyze_router
from .summary_pdf import router as pdf_summary_router
from .qna_pdf import router as pdf_qna_router
from .extract_pdf import router as pdf_extract_router
from .compare_pdf import router as pdf_compare_router

__all__ = [
    "pdf_analyze_router",
    "pdf_summary_router",
    "pdf_qna_router",
    "pdf_extract_router",
    "pdf_compare_router",
]

