import logging

from schemas import AiDetectImageRequest
from endpoints.ai_or_not.ai_analyze_image import analyze_image_from_url
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.detect_ai_image")


async def _logged_detect_ai_image(payload: AiDetectImageRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "detect_ai_image agent invoked chatId=%s userId=%s imageUrl=%s",
        payload.chat_id,
        user_id,
        payload.image_url,
    )
    result = await analyze_image_from_url(
        image_url=payload.image_url,
        user_id=user_id,
        chat_id=payload.chat_id or "",
        language=payload.language,
        mock=False,
    )
    return result


detect_ai_image_agent = handler_agent(
    name="detect_ai_image",
    description="Verilen görselin yapay zeka tarafından üretilip üretilmediğini analiz eder.",
    request_model=AiDetectImageRequest,
    handler=_logged_detect_ai_image,
)

__all__ = ["detect_ai_image_agent"]

