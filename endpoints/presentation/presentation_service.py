from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import firestore as firestore_client
from openai import OpenAI

from core.firebase import db
from schemas import PresentationRequest, SlideType

logger = logging.getLogger("pdf_read_refresh.presentation_service")


class PresentationService:
    """Service responsible for generating and storing presentations."""

    _instance: Optional["PresentationService"] = None

    def __init__(self) -> None:
        self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self._db = db

    @classmethod
    def get_instance(cls) -> "PresentationService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def get_presentation_templates(self) -> List[Dict[str, object]]:
        return [
            {
                "id": "startup_pitch",
                "name": "Startup Pitch Deck",
                "description": "A template for pitching your startup to investors.",
                "defaultSlideCount": 12,
                "includes": ["demo", "pricing", "competition", "roadmap"],
            },
            {
                "id": "product_launch",
                "name": "Product Launch",
                "description": "A template for launching a new product.",
                "defaultSlideCount": 10,
                "includes": ["demo", "pricing"],
            },
            {
                "id": "technical_deep_dive",
                "name": "Technical Deep Dive",
                "description": "A template for technical presentations.",
                "defaultSlideCount": 15,
                "includes": ["demo", "roadmap"],
            },
            {
                "id": "business_proposal",
                "name": "Business Proposal",
                "description": "A template for business proposals.",
                "defaultSlideCount": 8,
                "includes": ["pricing", "competition"],
            },
        ]

    async def generate_presentation(self, request: PresentationRequest, user_id: str) -> Dict[str, object]:
        logger.info("Generating presentation", extra={"userId": user_id, "topic": request.topic})

        if not request.topic.strip():
            raise ValueError("Topic is required")
        if not request.language.strip():
            raise ValueError("Language is required")
        if not request.audience.strip():
            raise ValueError("Audience is required")
        if not request.tone.strip():
            raise ValueError("Tone is required")

        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OpenAI API key not configured")

        presentation_id = f"pres_{int(time.time() * 1000)}_{random.randint(100000, 999999)}"

        presentation_content = await asyncio.to_thread(
            self._generate_presentation_content,
            request,
        )

        now = datetime.now(timezone.utc)
        created_at = now.isoformat()

        presentation = {
            "id": presentation_id,
            "title": presentation_content["title"],
            "slides": presentation_content["slides"],
            "metadata": {
                "language": request.language,
                "audience": request.audience,
                "tone": request.tone,
                "slideCount": request.slide_count,
                "brandName": request.brand_name,
                "colors": {
                    "primary": request.primary_color,
                    "secondary": request.secondary_color,
                    "darkBackground": request.dark_background_color,
                },
                "fonts": {
                    "primary": request.primary_font,
                    "secondary": request.secondary_font,
                },
                "includes": {
                    "demo": request.include_demo,
                    "pricing": request.include_pricing,
                    "competition": request.include_competition,
                    "roadmap": request.include_roadmap,
                },
            },
            "createdAt": created_at,
            "updatedAt": created_at,
        }

        await asyncio.to_thread(self._save_presentation_to_firestore, presentation, user_id)

        logger.info(
            "Presentation generated successfully",
            extra={"presentationId": presentation_id, "userId": user_id, "slideCount": len(presentation_content["slides"])}
        )

        return presentation

    async def get_user_presentations(self, user_id: str) -> List[Dict[str, object]]:
        if not user_id:
            return []

        return await asyncio.to_thread(self._fetch_user_presentations, user_id)

    # ----- Internal helpers -----

    def _save_presentation_to_firestore(self, presentation: Dict[str, object], user_id: str) -> None:
        if not self._db:
            logger.warning("Firestore client unavailable; skipping presentation persistence")
            return

        try:
            data = dict(presentation)
            data.update(
                {
                    "userId": user_id or "unknown",
                    "type": "presentation",
                    "createdAt": datetime.now(timezone.utc),
                    "updatedAt": datetime.now(timezone.utc),
                }
            )
            self._db.collection("presentations").document(presentation["id"]).set(data)
        except Exception as exc:  # pragma: no cover - Firestore failures are rare
            logger.exception("Failed to save presentation to Firestore: %s", exc)
            raise

    def _fetch_user_presentations(self, user_id: str) -> List[Dict[str, object]]:
        if not self._db:
            logger.warning("Firestore client unavailable; returning empty presentation list")
            return []

        try:
            query = (
                self._db.collection("presentations")
                .where("userId", "==", user_id)
                .where("type", "==", "presentation")
                .order_by("createdAt", direction=firestore_client.Query.DESCENDING)
            )
            presentations: List[Dict[str, object]] = []
            for doc in query.stream():
                data = doc.to_dict() or {}
                presentations.append(
                    {
                        "id": data.get("id", doc.id),
                        "title": data.get("title", "Untitled Presentation"),
                        "slides": data.get("slides", []),
                        "metadata": data.get("metadata", {}),
                        "createdAt": self._serialize_timestamp(data.get("createdAt")),
                        "updatedAt": self._serialize_timestamp(data.get("updatedAt")),
                    }
                )

            return presentations
        except Exception as exc:  # pragma: no cover - Firestore failures are rare
            logger.exception("Failed to fetch user presentations: %s", exc)
            raise

    def _serialize_timestamp(self, value) -> str:
        if value is None:
            return datetime.now(timezone.utc).isoformat()
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if hasattr(value, "to_datetime"):
            return value.to_datetime().astimezone(timezone.utc).isoformat()
        return str(value)

    def _generate_presentation_content(self, request: PresentationRequest) -> Dict[str, object]:
        system_prompt = self._build_system_prompt(request)
        user_prompt = self._build_user_prompt(request)

        logger.info(
            "Sending request to OpenAI",
            extra={
                "model": "gpt-5.1",
                "systemPromptLength": len(system_prompt),
                "userPromptLength": len(user_prompt),
            },
        )

        response = self._client.chat.completions.create(
            model="gpt-5.1",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_completion_tokens=4000,
        )

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise RuntimeError("No content generated from OpenAI")

        logger.debug("OpenAI response length: %s", len(content))
        return self._parse_presentation_content(content, request)

    def _build_system_prompt(self, request: PresentationRequest) -> str:
        return (
            "Sen dünya standartlarında bir **AI Sunum Yazarı** ve **Görsel Tasarım Direktörü**sün.\n\n"
            f"HEDEF: {request.topic} konusunda profesyonel bir sunum oluşturmak\n"
            f"Sunum dili: {request.language}\n"
            f"Hedef kitle: {request.audience}\n"
            f"Ton: {request.tone}\n"
            "Okunabilirlik: her slaytta ≤6 madde, her madde ≤12 kelime.\n\n"
            "MARKA / TASARIM\n"
            f"Renk paleti: Ana {request.primary_color}, ikincil {request.secondary_color}, koyu arka plan {request.dark_background_color}\n"
            f"Fontlar: Başlık {request.primary_font}, Metin {request.secondary_font}\n"
            "Görsel stil: minimal, modern, bol boşluklu, düz çizgili ikonlar\n"
            f"Logo veya marka ismi: \"{request.brand_name}\"\n"
            "Slaytlarda gereksiz metin olmasın; ana mesajlar kalın, önemli sayılar büyük puntolu.\n\n"
            f"YAPI (~{request.slide_count} slayt; ±%20 esnetilebilir)\n"
            "0. Kapak\n"
            "1. Problem\n"
            "2. Mevcut Çözümler & Eksikleri\n"
            "3. Bizim Çözüm\n"
            "4. Ürün Özellikleri\n"
            "5. Demo Akışı\n"
            "6. Mimari\n"
            "7. Güvenlik & Uyumluluk\n"
            "8. Performans & Ölçeklenebilirlik\n"
            "9. Yol Haritası\n"
            "10. Pazar / Persona\n"
            "11. Fiyatlandırma\n"
            "12. Başarı Örnekleri\n"
            "13. Rekabet Matrisi\n"
            "14. Riskler & Azaltım\n"
            "15. Kapanış / CTA\n\n"
            "İÇERİK KURALLARI\n"
            "- Slide başına 3–6 madde.\n"
            "- Her slaytta \"**Konuşmacı Notu:**\" (3–5 cümle) yer alsın.\n"
            "- Gerektiğinde \"**Görsel Notu:**\" (grafik/diyagram tanımı) ekle.\n"
            "- Türkçe içeriklerde KVKK, e-Devlet gibi terimleri yerelleştir.\n"
            "- Veriler yaklaşık aralıklarla yazılsın (örn. ~%30–35 artış).\n\n"
            "ÇIKTI FORMAT\n"
            "- Her slaytı `### Slide {num} — {başlık}` ile başlat.\n"
            "- Madde işaretleri `-` ile verilsin.\n"
            "- Slayt sonunda:\n"
            "  - \"**Konuşmacı Notu:** …\"\n"
            "  - \"**Görsel Notu:** …\" (gerektiğinde)\n"
            "- Tüm metinleri Markdown biçiminde üret."
        )

    def _build_user_prompt(self, request: PresentationRequest) -> str:
        extra_sections = []
        if request.include_demo:
            extra_sections.append("- Demo akışı dahil et")
        if request.include_pricing:
            extra_sections.append("- Fiyatlandırma bölümü dahil et")
        if request.include_competition:
            extra_sections.append("- Rekabet analizi dahil et")
        if request.include_roadmap:
            extra_sections.append("- Yol haritası dahil et")

        extras = "\n".join(extra_sections)

        return (
            "Aşağıdaki detaylara göre profesyonel bir sunum oluştur:\n\n"
            f"KONU: {request.topic}\n"
            f"Kısa özet: {request.topic} hakkında kapsamlı bir sunum\n"
            "Öne çıkanlar: Modern teknoloji, kullanıcı odaklı tasarım, ölçeklenebilir mimari\n"
            f"Pazarda fark: {request.topic} konusunda benzersiz yaklaşım\n\n"
            f"Slayt sayısı: {request.slide_count}\n"
            f"Dil: {request.language}\n"
            f"Hedef kitle: {request.audience}\n"
            f"Ton: {request.tone}\n\n"
            f"Ek özellikler:\n{extras}\n\n"
            "Lütfen tam sunumu üret."
        )

    def _parse_presentation_content(self, content: str, request: PresentationRequest) -> Dict[str, object]:
        slides: List[Dict[str, object]] = []
        current_slide: Optional[Dict[str, object]] = None
        slide_counter = 0

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("### Slide"):
                if current_slide:
                    slides.append(current_slide)

                title_match = re.search(r"### Slide \\d+ — (.+)", line)
                title = title_match.group(1).strip() if title_match else "Untitled Slide"
                current_slide = {
                    "id": slide_counter,
                    "title": title,
                    "content": [],
                    "speakerNotes": "",
                    "type": self._determine_slide_type(slide_counter, title),
                }
                slide_counter += 1
            elif line.startswith("- ") and current_slide is not None:
                current_slide.setdefault("content", []).append(line[2:])
            elif line.startswith("**Konuşmacı Notu:**") and current_slide is not None:
                current_slide["speakerNotes"] = line.replace("**Konuşmacı Notu:**", "").strip()
            elif line.startswith("**Görsel Notu:**") and current_slide is not None:
                current_slide["visualNotes"] = line.replace("**Görsel Notu:**", "").strip()

        if current_slide:
            slides.append(current_slide)

        return {
            "title": f"{request.topic} - {request.brand_name} Sunumu",
            "slides": slides,
        }

    def _determine_slide_type(self, slide_number: int, title: str) -> SlideType:
        lowered = title.lower()
        if slide_number == 0 or "kapak" in lowered or "cover" in lowered:
            return "cover"
        if "problem" in lowered:
            return "problem"
        if "çözüm" in lowered or "solution" in lowered:
            return "solution"
        if "özellik" in lowered or "feature" in lowered:
            return "features"
        if "demo" in lowered:
            return "demo"
        if "mimari" in lowered or "architecture" in lowered:
            return "architecture"
        if "güvenlik" in lowered or "security" in lowered:
            return "security"
        if "performans" in lowered or "performance" in lowered:
            return "performance"
        if "yol haritası" in lowered or "roadmap" in lowered:
            return "roadmap"
        if "pazar" in lowered or "market" in lowered:
            return "market"
        if "fiyat" in lowered or "pricing" in lowered:
            return "pricing"
        if "başarı" in lowered or "success" in lowered:
            return "success"
        if "rekabet" in lowered or "competition" in lowered:
            return "competition"
        if "risk" in lowered:
            return "risks"
        if "kapanış" in lowered or "cta" in lowered or "closing" in lowered:
            return "cta"
        return "features"


presentation_service = PresentationService.get_instance()

__all__ = ["presentation_service", "PresentationService"]


