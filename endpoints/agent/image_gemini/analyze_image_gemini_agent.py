import logging

from schemas import GeminiImageAnalyzeRequest
from endpoints.generate_image.analyze_image_gemini import analyze_gemini_image
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.image_gemini.analyze")


async def _logged_analyze_image(payload: GeminiImageAnalyzeRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "analyze_image_gemini agent handler invoked userId=%s imageUrl=%s promptPreview=%s",
        user_id,
        payload.image_url,
        (payload.prompt or "")[:120],
    )
    return await analyze_gemini_image(payload, request)


analyze_image_gemini_agent = handler_agent(
    name="analyze_image_gemini",
    description="Gemini ile bir görseli analiz eder ve metin çıktısı döner.",
    request_model=GeminiImageAnalyzeRequest,
    handler=_logged_analyze_image,
)

__all__ = ["analyze_image_gemini_agent"]

