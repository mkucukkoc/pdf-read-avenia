from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SlideType = Literal[
    "cover",
    "problem",
    "solution",
    "features",
    "demo",
    "architecture",
    "security",
    "performance",
    "roadmap",
    "market",
    "pricing",
    "success",
    "competition",
    "risks",
    "cta",
]


class PresentationRequest(BaseModel):
    topic: str
    language: str
    audience: str
    tone: str
    slide_count: int = Field(..., alias="slideCount", ge=5, le=30)
    brand_name: str = Field(..., alias="brandName")
    primary_color: str = Field(..., alias="primaryColor")
    secondary_color: str = Field(..., alias="secondaryColor")
    dark_background_color: str = Field(..., alias="darkBackgroundColor")
    primary_font: str = Field(..., alias="primaryFont")
    secondary_font: str = Field(..., alias="secondaryFont")
    include_demo: bool = Field(False, alias="includeDemo")
    include_pricing: bool = Field(False, alias="includePricing")
    include_competition: bool = Field(False, alias="includeCompetition")
    include_roadmap: bool = Field(False, alias="includeRoadmap")

    model_config = ConfigDict(populate_by_name=True)


class Slide(BaseModel):
    id: int
    title: str
    content: List[str]
    speaker_notes: str = Field(..., alias="speakerNotes")
    visual_notes: Optional[str] = Field(default=None, alias="visualNotes")
    type: SlideType

    model_config = ConfigDict(populate_by_name=True, ser_json_timedelta="iso8601")


class PresentationMetadata(BaseModel):
    language: str
    audience: str
    tone: str
    slide_count: int = Field(..., alias="slideCount")
    brand_name: str = Field(..., alias="brandName")
    colors: Dict[str, str]
    fonts: Dict[str, str]
    includes: Dict[str, bool]

    model_config = ConfigDict(populate_by_name=True)


class PresentationResponse(BaseModel):
    id: str
    title: str
    slides: List[Slide]
    metadata: PresentationMetadata
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class ChatMessagePayload(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    file_url: Optional[str] = Field(default=None, alias="fileUrl")
    metadata: Optional[Dict[str, Any]] = None
    message_id: Optional[str] = Field(default=None, alias="messageId")

    model_config = ConfigDict(populate_by_name=True)


class ChatRequestPayload(BaseModel):
    messages: List[ChatMessagePayload]
    chat_id: str = Field(..., alias="chatId")
    has_image: bool = Field(default=False, alias="hasImage")
    image_file_url: Optional[str] = Field(default=None, alias="imageFileUrl")
    language: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class TextToSpeechRequest(BaseModel):
    messages: List[ChatMessagePayload]


class ImageEditRequest(BaseModel):
    image_url: str = Field(..., alias="imageUrl")
    prompt: str
    chat_id: Optional[str] = Field(default=None, alias="chatId")
    language: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)




class GeminiImageRequest(BaseModel):
    prompt: str
    chat_id: Optional[str] = Field(default=None, alias="chatId")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    use_google_search: bool = Field(default=False, alias="useGoogleSearch")
    aspect_ratio: Optional[str] = Field(default=None, alias="aspectRatio")
    model: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class GeminiImageEditRequest(BaseModel):
    prompt: str
    image_url: Optional[str] = Field(default=None, alias="imageUrl")
    chat_id: Optional[str] = Field(default=None, alias="chatId")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    # Opsiyonel model seçimi; yoksa env ya da fallback kullanılır
    model: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class GeminiVideoRequest(BaseModel):
    prompt: str
    chat_id: Optional[str] = Field(default=None, alias="chatId")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    duration: Optional[int] = 8
    resolution: Optional[str] = "1080p"

    model_config = ConfigDict(populate_by_name=True)

class CreateChatRequest(BaseModel):
    title: Optional[str] = None


class AgentDispatchRequest(BaseModel):
    prompt: Optional[str] = None
    chat_id: Optional[str] = Field(default=None, alias="chatId")
    language: Optional[str] = None
    conversation: List[ChatMessagePayload] = Field(default_factory=list)
    file_url: Optional[str] = Field(default=None, alias="fileUrl")
    file_urls: Optional[List[str]] = Field(default=None, alias="fileUrls")
    file1: Optional[str] = None
    file2: Optional[str] = None
    question: Optional[str] = None
    file_id: Optional[str] = Field(default=None, alias="fileId")
    file_name: Optional[str] = Field(default=None, alias="fileName")
    target_language: Optional[str] = Field(default=None, alias="targetLanguage")
    source_language: Optional[str] = Field(default=None, alias="sourceLanguage")
    user_id: Optional[str] = Field(default=None, alias="userId")
    stream: bool = False
    parameters: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class PdfAnalyzeRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfSummaryRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    summary_level: Optional[str] = Field(default="basic", alias="summaryLevel")
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfQnaRequest(BaseModel):
    file_id: Optional[str] = Field(default=None, alias="fileId")
    file_url: Optional[str] = Field(default=None, alias="fileUrl")
    question: str
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfExtractRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfCompareRequest(BaseModel):
    file1: str = Field(..., alias="file1")
    file2: str = Field(..., alias="file2")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfRewriteRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    style: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfClassifyRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    labels: Optional[list[str]] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfMultiAnalyzeRequest(BaseModel):
    file_urls: list[str] = Field(..., alias="fileUrls")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfOcrExtractRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfLayoutRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfDeepExtractRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    fields: Optional[list[str]] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfGroundedSearchRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    question: str = Field(..., alias="question")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfTranslateRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    target_language: str = Field(..., alias="targetLanguage")
    source_language: Optional[str] = Field(default=None, alias="sourceLanguage")
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


class PdfStructureExportRequest(BaseModel):
    file_url: str = Field(..., alias="fileUrl")
    chat_id: str = Field(..., alias="chatId")
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    prompt: Optional[str] = None
    stream: bool = False

    model_config = ConfigDict(populate_by_name=True)


__all__ = [
    "PresentationRequest",
    "Slide",
    "PresentationMetadata",
    "PresentationResponse",
    "SlideType",
    "ChatMessagePayload",
    "ChatRequestPayload",
    "TextToSpeechRequest",
    "ImageEditRequest",
    "GeminiImageRequest",
    "GeminiImageEditRequest",
    "GeminiVideoRequest",
    "CreateChatRequest",
    "AgentDispatchRequest",
    "PdfAnalyzeRequest",
    "PdfSummaryRequest",
    "PdfQnaRequest",
    "PdfExtractRequest",
    "PdfCompareRequest",
    "PdfRewriteRequest",
    "PdfClassifyRequest",
    "PdfMultiAnalyzeRequest",
    "PdfOcrExtractRequest",
    "PdfLayoutRequest",
    "PdfDeepExtractRequest",
    "PdfGroundedSearchRequest",
    "PdfTranslateRequest",
    "PdfStructureExportRequest",
]
