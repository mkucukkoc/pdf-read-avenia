from schemas import PdfQnaRequest
from endpoints.files_pdf.qna_pdf import qna_pdf
from endpoints.agent.baseAgent import handler_agent

qna_pdf_agent = handler_agent(
    name="pdf_qna",
    description="PDF üzerinde soru-cevap işlemleri yapar.",
    request_model=PdfQnaRequest,
    handler=qna_pdf,
)

__all__ = ["qna_pdf_agent"]

