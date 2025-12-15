from schemas import PdfAnalyzeRequest
from endpoints.files_pdf.analyze_pdf import analyze_pdf
from endpoints.agent.baseAgent import handler_agent

analyze_pdf_agent = handler_agent(
    name="pdf_analyze",
    description="PDF dosyalarını detaylı analiz eder.",
    request_model=PdfAnalyzeRequest,
    handler=analyze_pdf,
)

__all__ = ["analyze_pdf_agent"]

