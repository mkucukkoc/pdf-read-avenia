from .chat import router as chat_router
from .presentation import router as presentation_router
from .gemini_image import router as gemini_image_router
# from .image_edit import router as image_edit_router  # Disabled for now

__all__ = [
    "chat_router",
    "presentation_router",
    "gemini_image_router",
    # "image_edit_router",
]
