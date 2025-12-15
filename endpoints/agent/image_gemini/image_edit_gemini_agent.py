import logging

from schemas import GeminiImageEditRequest
from endpoints.generate_image.edit_image_gemini import edit_gemini_image
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.image_gemini.edit")


async def _logged_image_edit(payload: GeminiImageEditRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "image_edit_gemini agent handler invoked userId=%s imageUrl=%s promptPreview=%s",
        user_id,
        payload.image_url,
        (payload.prompt or "")[:120],
    )
    return await edit_gemini_image(payload, request)


image_edit_gemini_agent = handler_agent(
    name="image_edit_gemini",
    description="Gemini ile tek adımlı görüntü düzenleme yapar.",
    request_model=GeminiImageEditRequest,
    handler=_logged_image_edit,
)

__all__ = ["image_edit_gemini_agent"]

