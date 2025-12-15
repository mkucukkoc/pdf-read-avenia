from schemas import GeminiImageRequest
from endpoints.generate_image.generateImageGeminiSearch import generate_gemini_image_with_search
from endpoints.agent.baseAgent import handler_agent

generate_image_gemini_search_agent = handler_agent(
    name="generate_image_gemini_search",
    description="Gemini ile Google Search destekli görsel üretir.",
    request_model=GeminiImageRequest,
    handler=generate_gemini_image_with_search,
)

__all__ = ["generate_image_gemini_search_agent"]

