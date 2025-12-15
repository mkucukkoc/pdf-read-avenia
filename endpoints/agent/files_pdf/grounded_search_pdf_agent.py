from schemas import PdfGroundedSearchRequest
from endpoints.files_pdf.grounded_search_pdf import grounded_search_pdf
from endpoints.agent.baseAgent import handler_agent

grounded_search_pdf_agent = handler_agent(
    name="pdf_grounded_search",
    description="PDF içerisinde grounded search yapar.",
    request_model=PdfGroundedSearchRequest,
    handler=grounded_search_pdf,
)

__all__ = ["grounded_search_pdf_agent"]

