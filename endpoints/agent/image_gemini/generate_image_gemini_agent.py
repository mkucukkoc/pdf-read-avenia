import logging

from schemas import GeminiImageRequest
from endpoints.generate_image.gemini_image import generate_gemini_image
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.image_gemini.generate")


async def _logged_generate_image(payload: GeminiImageRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "generate_image_gemini agent handler invoked userId=%s promptPreview=%s style=%s",
        user_id,
        (payload.prompt or "")[:120],
        payload.style,
    )
    return await generate_gemini_image(payload, request)


generate_image_gemini_agent = handler_agent(
    name="generate_image_gemini",
    description="Gemini ile görsel üretir.",
    request_model=GeminiImageRequest,
    handler=_logged_generate_image,
)

__all__ = ["generate_image_gemini_agent"]

