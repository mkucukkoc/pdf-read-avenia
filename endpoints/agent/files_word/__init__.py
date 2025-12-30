from .summary_word_agent import summary_word_agent
from .analyze_word_agent import analyze_word_agent
from .qna_word_agent import qna_word_agent
from .translate_word_agent import translate_word_agent
from .rewrite_word_agent import rewrite_word_agent
from .compare_word_agent import compare_word_agent
from .extract_word_agent import extract_word_agent
from .classify_word_agent import classify_word_agent
from .multi_analyze_word_agent import multi_analyze_word_agent
from .ocr_extract_word_agent import ocr_extract_word_agent
from .layout_word_agent import layout_word_agent
from .deep_extract_word_agent import deep_extract_word_agent
from .grounded_search_word_agent import grounded_search_word_agent
from .structure_export_word_agent import structure_export_word_agent

word_agent_functions = [
    summary_word_agent,
    analyze_word_agent,
    qna_word_agent,
    translate_word_agent,
    rewrite_word_agent,
    compare_word_agent,
    extract_word_agent,
    classify_word_agent,
    multi_analyze_word_agent,
    ocr_extract_word_agent,
    layout_word_agent,
    deep_extract_word_agent,
    grounded_search_word_agent,
    structure_export_word_agent,
]

__all__ = [
    "word_agent_functions",
    "summary_word_agent",
    "analyze_word_agent",
    "qna_word_agent",
    "translate_word_agent",
    "rewrite_word_agent",
    "compare_word_agent",
    "extract_word_agent",
    "classify_word_agent",
    "multi_analyze_word_agent",
    "ocr_extract_word_agent",
    "layout_word_agent",
    "deep_extract_word_agent",
    "grounded_search_word_agent",
    "structure_export_word_agent",
]

