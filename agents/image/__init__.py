"""Backend image agents (Gemini) executing the same logic as frontend agents.

These helpers call the internal Gemini image helpers used by FastAPI routes,
so behavior matches the existing /api/v1/image endpoints without going
through HTTP.
"""

from .executor import (
    execute_generate_image,
    execute_generate_image_search,
    execute_edit_image,
)

__all__ = [
    "execute_generate_image",
    "execute_generate_image_search",
    "execute_edit_image",
]


