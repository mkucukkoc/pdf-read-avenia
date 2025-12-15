from schemas import PdfDeepExtractRequest
from endpoints.files_pdf.deepextract_pdf import deepextract_pdf
from endpoints.agent.baseAgent import handler_agent

deep_extract_pdf_agent = handler_agent(
    name="pdf_deepextract",
    description="PDF içerisindeki belirli alanları derinlemesine çıkarır.",
    request_model=PdfDeepExtractRequest,
    handler=deepextract_pdf,
)

__all__ = ["deep_extract_pdf_agent"]

