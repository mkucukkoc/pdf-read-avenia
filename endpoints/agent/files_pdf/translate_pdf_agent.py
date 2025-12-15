from schemas import PdfTranslateRequest
from endpoints.files_pdf.translate_pdf import translate_pdf
from endpoints.agent.baseAgent import handler_agent

translate_pdf_agent = handler_agent(
    name="pdf_translate",
    description="PDF içeriğini hedef dile çevirir.",
    request_model=PdfTranslateRequest,
    handler=translate_pdf,
)

__all__ = ["translate_pdf_agent"]

