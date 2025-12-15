from schemas import PdfOcrExtractRequest
from endpoints.files_pdf.ocr_extract_pdf import ocr_extract_pdf
from endpoints.agent.baseAgent import handler_agent

ocr_extract_pdf_agent = handler_agent(
    name="pdf_ocr_extract",
    description="PDF içerisindeki metni OCR ile çıkarır.",
    request_model=PdfOcrExtractRequest,
    handler=ocr_extract_pdf,
)

__all__ = ["ocr_extract_pdf_agent"]

