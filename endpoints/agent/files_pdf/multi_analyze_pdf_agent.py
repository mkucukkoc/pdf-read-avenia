from schemas import PdfMultiAnalyzeRequest
from endpoints.files_pdf.multianalyze_pdf import multianalyze_pdf
from endpoints.agent.baseAgent import handler_agent

multi_analyze_pdf_agent = handler_agent(
    name="pdf_multianalyze",
    description="Birden fazla PDF dosyasını birlikte analiz eder.",
    request_model=PdfMultiAnalyzeRequest,
    handler=multianalyze_pdf,
)

__all__ = ["multi_analyze_pdf_agent"]

