import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, Request

from tests.pdf import config, cases

logger = logging.getLogger("pdf_read_refresh.files_pdf.test_runner")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDFTest"])


def _merge_payload(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = base.copy()
    merged.update({k: v for k, v in override.items() if v is not None})
    return merged


@router.post("/test_pdf")
async def run_pdf_tests(
    request: Request,
    body: Optional[Dict[str, Any]] = Body(default=None),
) -> Dict[str, Any]:
    """
    Runs PDF endpoint test cases sequentially inside the running app and returns a JSON report.
    Accepts optional overrides:
    - token: bearer token override
    - cases: list of case names to run (defaults to all; if file1/file2 passed without cases -> only compare)
    - payload: common override applied to all selected cases
    - payloads: per-case override dict, e.g. {"compare": {...}}
    - headers: extra headers to add
    - Direct compare payload (file1/file2/...) without 'cases' will run only compare with those fields.
    """
    app = request.app
    body = body or {}

    token_override = body.get("token")
    extra_headers = body.get("headers") or {}
    common_override = body.get("payload") or {}
    per_case_overrides: Dict[str, Dict[str, Any]] = body.get("payloads") or {}

    # Case selection
    requested_cases = body.get("cases")
    if requested_cases:
        selected_cases = [c for c in requested_cases if c in [case["name"] for case in cases.TEST_CASES]]
    elif any(k in body for k in ("file1", "file2")):
        selected_cases = ["pdf_compare"]
    else:
        selected_cases = [case["name"] for case in cases.TEST_CASES]

    headers = {
        "Authorization": f"Bearer {token_override or config.TEST_BEARER_TOKEN}",
        "Accept-Language": config.TEST_LANGUAGE,
        "Content-Type": "application/json",
        **extra_headers,
    }

    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        for case in cases.TEST_CASES:
            name = case["name"]
            method = case["method"]
            path = case["path"]
            if name not in selected_cases:
                continue

            per_case_override = per_case_overrides.get(name) or {}

            # If compare-only direct payload provided, use it as per-case override
            direct_compare_override: Dict[str, Any] = {}
            if name == "pdf_compare" and not requested_cases and any(k in body for k in ("file1", "file2")):
                direct_compare_override = {k: v for k, v in body.items() if k not in ("token", "cases", "payload", "payloads", "headers")}

            try:
                payload = cases.get_payload(case["payload"])
                payload = _merge_payload(payload, common_override)
                payload = _merge_payload(payload, per_case_override)
                if direct_compare_override:
                    payload = _merge_payload(payload, direct_compare_override)
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


