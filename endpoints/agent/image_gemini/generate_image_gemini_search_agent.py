import logging

from schemas import GeminiImageRequest
from endpoints.generate_image.generateImageGeminiSearch import generate_gemini_image_with_search
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.image_gemini.generate_search")


async def _logged_generate_image_search(payload: GeminiImageRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "generate_image_gemini_search agent handler invoked userId=%s promptPreview=%s searchMode=%s",
        user_id,
        (payload.prompt or "")[:120],
        payload.search_mode,
    )
    return await generate_gemini_image_with_search(payload, request)


generate_image_gemini_search_agent = handler_agent(
    name="generate_image_gemini_search",
    description="Gemini ile Google Search destekli görsel üretir.",
    request_model=GeminiImageRequest,
    handler=_logged_generate_image_search,
)

__all__ = ["generate_image_gemini_search_agent"]

