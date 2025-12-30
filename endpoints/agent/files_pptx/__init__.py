from .summary_pptx_agent import summary_pptx_agent
from .analyze_pptx_agent import analyze_pptx_agent
from .qna_pptx_agent import qna_pptx_agent
from .translate_pptx_agent import translate_pptx_agent
from .rewrite_pptx_agent import rewrite_pptx_agent
from .compare_pptx_agent import compare_pptx_agent
from .deep_extract_pptx_agent import deep_extract_pptx_agent
from .grounded_search_pptx_agent import grounded_search_pptx_agent
from .structure_export_pptx_agent import structure_export_pptx_agent
from .extract_pptx_agent import extract_pptx_agent
from .classify_pptx_agent import classify_pptx_agent
from .multi_analyze_pptx_agent import multi_analyze_pptx_agent
from .ocr_extract_pptx_agent import ocr_extract_pptx_agent
from .layout_pptx_agent import layout_pptx_agent

pptx_agent_functions = [
    summary_pptx_agent,
    analyze_pptx_agent,
    qna_pptx_agent,
    translate_pptx_agent,
    rewrite_pptx_agent,
    compare_pptx_agent,
    deep_extract_pptx_agent,
    grounded_search_pptx_agent,
    structure_export_pptx_agent,
    extract_pptx_agent,
    classify_pptx_agent,
    multi_analyze_pptx_agent,
    ocr_extract_pptx_agent,
    layout_pptx_agent,
]

__all__ = [
    "pptx_agent_functions",
    "summary_pptx_agent",
    "analyze_pptx_agent",
    "qna_pptx_agent",
    "translate_pptx_agent",
    "rewrite_pptx_agent",
    "compare_pptx_agent",
    "deep_extract_pptx_agent",
    "grounded_search_pptx_agent",
    "structure_export_pptx_agent",
    "extract_pptx_agent",
    "classify_pptx_agent",
    "multi_analyze_pptx_agent",
    "ocr_extract_pptx_agent",
    "layout_pptx_agent",
]

