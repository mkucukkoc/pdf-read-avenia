from schemas import PdfExtractRequest
from endpoints.files_pdf.extract_pdf import extract_pdf
from endpoints.agent.baseAgent import handler_agent

extract_pdf_agent = handler_agent(
    name="pdf_extract",
    description="PDF içerisindeki önemli bilgileri çıkarır.",
    request_model=PdfExtractRequest,
    handler=extract_pdf,
)

__all__ = ["extract_pdf_agent"]

