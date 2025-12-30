import logging

from schemas import DocMultiAnalyzeRequest
from endpoints.files_word.multi_analyze_word import multi_analyze_word
from endpoints.agent.baseAgent import handler_agent
from endpoints.agent.utils import get_request_user_id

logger = logging.getLogger("pdf_read_refresh.agent.files_word.multi_analyze")


async def _logged_multi_analyze_word(payload: DocMultiAnalyzeRequest, request):
    user_id = get_request_user_id(request)
    logger.info(
        "word_multi_analyze agent handler invoked chatId=%s userId=%s fileCount=%s",
        payload.chat_id,
        user_id,
        len(payload.file_urls or []),
    )
    return await multi_analyze_word(payload, request)


multi_analyze_word_agent = handler_agent(
    name="word_multi_analyze",
    description="Birden fazla Word dokümanını birlikte analiz eder; .docx/.doc içerikler.",
    request_model=DocMultiAnalyzeRequest,
    handler=_logged_multi_analyze_word,
)

__all__ = ["multi_analyze_word_agent"]

