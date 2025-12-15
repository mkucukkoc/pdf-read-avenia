from .analyze_pdf_agent import analyze_pdf_agent
from .summary_pdf_agent import summary_pdf_agent
from .qna_pdf_agent import qna_pdf_agent
from .extract_pdf_agent import extract_pdf_agent
from .compare_pdf_agent import compare_pdf_agent
from .rewrite_pdf_agent import rewrite_pdf_agent
from .classify_pdf_agent import classify_pdf_agent
from .multi_analyze_pdf_agent import multi_analyze_pdf_agent
from .ocr_extract_pdf_agent import ocr_extract_pdf_agent
from .layout_pdf_agent import layout_pdf_agent
from .deep_extract_pdf_agent import deep_extract_pdf_agent
from .grounded_search_pdf_agent import grounded_search_pdf_agent
from .translate_pdf_agent import translate_pdf_agent
from .structure_export_pdf_agent import structure_export_pdf_agent

pdf_agent_functions = [
    analyze_pdf_agent,
    summary_pdf_agent,
    qna_pdf_agent,
    extract_pdf_agent,
    compare_pdf_agent,
    rewrite_pdf_agent,
    classify_pdf_agent,
    multi_analyze_pdf_agent,
    ocr_extract_pdf_agent,
    layout_pdf_agent,
    deep_extract_pdf_agent,
    grounded_search_pdf_agent,
    translate_pdf_agent,
    structure_export_pdf_agent,
]

__all__ = [
    "pdf_agent_functions",
    "analyze_pdf_agent",
    "summary_pdf_agent",
    "qna_pdf_agent",
    "extract_pdf_agent",
    "compare_pdf_agent",
    "rewrite_pdf_agent",
    "classify_pdf_agent",
    "multi_analyze_pdf_agent",
    "ocr_extract_pdf_agent",
    "layout_pdf_agent",
    "deep_extract_pdf_agent",
    "grounded_search_pdf_agent",
    "translate_pdf_agent",
    "structure_export_pdf_agent",
]

