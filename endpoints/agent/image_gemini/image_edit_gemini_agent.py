from schemas import GeminiImageEditRequest
from endpoints.generate_image.edit_image_gemini import edit_gemini_image
from endpoints.agent.baseAgent import handler_agent

image_edit_gemini_agent = handler_agent(
    name="image_edit_gemini",
    description="Gemini ile tek adımlı görüntü düzenleme yapar.",
    request_model=GeminiImageEditRequest,
    handler=edit_gemini_image,
)

__all__ = ["image_edit_gemini_agent"]

