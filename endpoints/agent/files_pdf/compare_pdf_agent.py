from schemas import PdfCompareRequest
from endpoints.files_pdf.compare_pdf import compare_pdf
from endpoints.agent.baseAgent import handler_agent

compare_pdf_agent = handler_agent(
    name="pdf_compare",
    description="İki PDF dosyasını farklarını belirleyerek karşılaştırır.",
    request_model=PdfCompareRequest,
    handler=compare_pdf,
)

__all__ = ["compare_pdf_agent"]

