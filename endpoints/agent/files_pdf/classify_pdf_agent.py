from schemas import PdfClassifyRequest
from endpoints.files_pdf.classify_pdf import classify_pdf
from endpoints.agent.baseAgent import handler_agent

classify_pdf_agent = handler_agent(
    name="pdf_classify",
    description="PDF içeriğini belirtilen kriterlere göre sınıflandırır.",
    request_model=PdfClassifyRequest,
    handler=classify_pdf,
)

__all__ = ["classify_pdf_agent"]

