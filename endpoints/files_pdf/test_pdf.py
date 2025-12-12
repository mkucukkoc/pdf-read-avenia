import json
import logging
import time
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Request

from tests.pdf import config, cases

logger = logging.getLogger("pdf_read_refresh.files_pdf.test_runner")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDFTest"])


@router.get("/test_pdf")
async def run_pdf_tests(request: Request) -> Dict[str, Any]:
    """
    Runs all PDF endpoint test cases sequentially inside the running app and returns a JSON report.
    """
    app = request.app
    headers = {
        "Authorization": f"Bearer {config.TEST_BEARER_TOKEN}",
        "Accept-Language": config.TEST_LANGUAGE,
        "Content-Type": "application/json",
    }

    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        for case in cases.TEST_CASES:
            name = case["name"]
            method = case["method"]
            path = case["path"]
            try:
                payload = cases.get_payload(case["payload"])
            except Exception as exc:  # pragma: no cover - defensive
                results.append(
                    {
                        "endpoint": name,
                        "path": path,
                        "method": method,
                        "success": False,
                        "error": f"Payload build failed: {exc}",
                        "requestPayload": None,
                    }
                )
                continue

            start = time.perf_counter()
            resp = await client.request(method, path, headers=headers, json=payload)
            duration_ms = int((time.perf_counter() - start) * 1000)

            try:
                resp_json = resp.json()
            except Exception:
                resp_json = {"raw": resp.text}

            # Extract a brief content preview if available
            preview = None
            for key in ("analysis", "summary", "answer", "data", "differences", "rewrite", "classification", "text", "layout", "translation", "structure"):
                if isinstance(resp_json, dict) and key in resp_json:
                    val = resp_json.get(key)
                    if isinstance(val, str):
                        preview = val[:400]
                    break

            result = {
                "endpoint": name,
                "path": path,
                "method": method,
                "requestPayload": payload,
                "statusCode": resp.status_code,
                "success": resp.status_code < 300 and bool(resp_json if isinstance(resp_json, dict) else False),
                "durationMs": duration_ms,
                "response": resp_json,
                "responsePreview": preview,
            }

            if resp.is_error:
                result["error"] = resp_json

            # Log each case with request/response for traceability
            logger.info(
                "PDF test case executed",
                extra={
                    "endpoint": name,
                    "path": path,
                    "method": method,
                    "payload": payload,
                    "status": resp.status_code,
                    "durationMs": duration_ms,
                    "preview": preview,
                },
            )

            results.append(result)

    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r.get("success")),
        "failed": sum(1 for r in results if not r.get("success")),
    }

    return {"summary": summary, "results": results}


