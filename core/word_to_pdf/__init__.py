"""
Deprecated word_to_pdf module.
Conversion was removed; kept to avoid import errors.
Returns original bytes and a default PDF filename.
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def convert_word_bytes_to_pdf_bytes(content: bytes, suffix: str = ".pdf") -> Tuple[bytes, str]:
    """
    Deprecated stub: returns input bytes unchanged with a default filename.
    """
    logger.warning("convert_word_bytes_to_pdf_bytes is deprecated; returning original bytes")
    filename = f"document{suffix}" if suffix else "document.pdf"
    return content, filename


