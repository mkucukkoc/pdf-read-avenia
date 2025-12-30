import logging

from schemas import DocAnalyzeRequest
from endpoints.files_word.analyze_word import analyze_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.analyze")


async def _logged_analyze_word(payload: DocAnalyzeRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_analyze agent handler invoked chatId=%s userId=%s fileUrl=%s fileName=%s",
        payload.chat_id,
        user_id,
        payload.file_url,
        payload.file_name,
    )
    return await analyze_word(payload, request)


analyze_word_agent = handler_agent(
    name="word_analyze",
    description="Word dokümanlarını detaylı analiz eder; .docx/.doc içerikler.",
    request_model=DocAnalyzeRequest,
    handler=_logged_analyze_word,
)

__all__ = ["analyze_word_agent"]

