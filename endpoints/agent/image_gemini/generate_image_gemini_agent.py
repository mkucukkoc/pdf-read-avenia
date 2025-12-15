from schemas import GeminiImageRequest
from endpoints.generate_image.gemini_image import generate_gemini_image
from endpoints.agent.baseAgent import handler_agent

generate_image_gemini_agent = handler_agent(
    name="generate_image_gemini",
    description="Gemini ile görsel üretir.",
    request_model=GeminiImageRequest,
    handler=generate_gemini_image,
)

__all__ = ["generate_image_gemini_agent"]

