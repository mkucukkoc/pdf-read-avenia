from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

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


class CreateChatRequest(BaseModel):
    title: Optional[str] = None


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
    "CreateChatRequest",
]
