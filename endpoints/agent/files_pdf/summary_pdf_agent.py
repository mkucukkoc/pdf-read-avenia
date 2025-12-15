from schemas import PdfSummaryRequest
from endpoints.files_pdf.summary_pdf import summary_pdf
from endpoints.agent.baseAgent import handler_agent

summary_pdf_agent = handler_agent(
    name="pdf_summary",
    description="PDF içerisinden özet çıkarır.",
    request_model=PdfSummaryRequest,
    handler=summary_pdf,
)

__all__ = ["summary_pdf_agent"]

