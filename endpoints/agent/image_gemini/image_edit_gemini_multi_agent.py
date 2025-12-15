from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from schemas import GeminiImageEditRequest
from endpoints.generate_image.edit_image_gemini import edit_gemini_image
from endpoints.agent.baseAgent import BaseAgent
from endpoints.agent.utils import build_internal_request

logger = logging.getLogger("pdf_read_refresh.agent.image_edit_multi")


class ImageEditGeminiMultiAgent(BaseAgent):
    name = "image_edit_gemini_multi"
    description = (
        "Gemini ile aynı görsel üzerinde ardışık çoklu düzenleme adımları uygular. "
        "Arka arkaya birden fazla prompt çalıştırmak için kullanılır."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Tek adımlı düzenleme talimatı"},
            "steps": {
                "type": "array",
                "description": "Birden fazla düzenleme adımı için talimat listesi",
                "items": {"type": "string"},
            },
            "imageFileUrl": {"type": "string", "description": "Başlangıç görüntüsü URL'i"},
            "chatId": {"type": "string", "description": "Sohbet ID'si"},
            "fileName": {"type": "string", "description": "Opsiyonel çıktı dosya adı"},
            "language": {"type": "string", "description": "Dil kodu"},
        },
        "required": ["imageFileUrl", "chatId"],
        "additionalProperties": False,
    }

    async def execute(self, args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        prompt = (args.get("prompt") or "").strip()
        steps = [step.strip() for step in (args.get("steps") or []) if isinstance(step, str) and step.strip()]
        image_url = args.get("imageFileUrl") or args.get("imageUrl")
        chat_id = args.get("chatId")
        file_name = args.get("fileName")
        language = args.get("language")

        if not chat_id:
            return {"error": "chatId is required."}

        if not image_url or not isinstance(image_url, str) or not image_url.startswith(("http://", "https://")):
            return {"error": "Valid imageFileUrl is required."}

        placeholder_tokens = ("your-image-url", "example.com/your-image-url")
        if any(token in image_url for token in placeholder_tokens):
            return {"error": "Please provide a valid image URL to edit."}

        instructions: List[str] = []
        if prompt:
            instructions.append(prompt)
        instructions.extend(steps)

        if not instructions:
            return {"error": "At least one editing instruction (prompt or steps) is required."}

        current_image_url = image_url
        last_response: Optional[Dict[str, Any]] = None
        internal_request = build_internal_request(user_id)

        logger.info(
            "Starting multi-step image edit chatId=%s userId=%s stepCount=%s imageUrl=%s",
            chat_id,
            user_id,
            len(instructions),
            image_url,
        )

        for idx, instruction in enumerate(instructions):
            request_model = GeminiImageEditRequest(
                prompt=instruction,
                image_url=current_image_url,
                chat_id=chat_id,
                file_name=file_name,
                language=language,
            )

            logger.info(
                "Executing image edit step chatId=%s step=%s promptPreview=%s",
                chat_id,
                idx + 1,
                instruction[:120],
            )

            try:
                result = await edit_gemini_image(request_model, internal_request)
            except HTTPException as exc:
                logger.error(
                    "Image edit step failed chatId=%s step=%s status=%s detail=%s",
                    chat_id,
                    idx + 1,
                    exc.status_code,
                    exc.detail,
                )
                raise
            except Exception as exc:  # pragma: no cover
                logger.exception("Unexpected error during image edit step chatId=%s step=%s", chat_id, idx + 1)
                raise HTTPException(
                    status_code=500,
                    detail={"success": False, "error": "image_edit_failed", "message": str(exc)},
                ) from exc

            if not result.get("success"):
                message = result.get("message") or "Image edit failed."
                logger.warning(
                    "Image edit step returned error chatId=%s step=%s message=%s",
                    chat_id,
                    idx + 1,
                    message,
                )
                return {"error": message, "details": result}

            current_image_url = result.get("imageUrl") or result.get("dataUrl") or current_image_url
            last_response = result

        logger.info(
            "Multi-step image edit completed chatId=%s stepCount=%s finalUrl=%s",
            chat_id,
            len(instructions),
            current_image_url,
        )

        return {
            "handled": True,
            "imageUrl": current_image_url,
            "dataUrl": last_response.get("dataUrl") if last_response else None,
            "model": last_response.get("model") if last_response else None,
            "multiStep": len(instructions) > 1,
            "stepsCount": len(instructions),
        }


image_edit_gemini_multi_agent = ImageEditGeminiMultiAgent()

__all__ = ["image_edit_gemini_multi_agent"]

