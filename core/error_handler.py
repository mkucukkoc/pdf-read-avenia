import logging
import json
import traceback
from pathlib import Path
from typing import Union
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

# Configure logging
_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "app.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(_LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class CustomHTTPException(HTTPException):
    def __init__(self, status_code: int, detail: str, error_code: str = None):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code

class ValidationError(Exception):
    def __init__(self, message: str, field: str = None):
        self.message = message
        self.field = field
        super().__init__(self.message)

class BusinessLogicError(Exception):
    def __init__(self, message: str, error_code: str = None):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)

class ExternalServiceError(Exception):
    def __init__(self, message: str, service: str = None):
        self.message = message
        self.service = service
        super().__init__(self.message)

def create_error_response(
    status_code: int,
    message: str,
    error_code: str = None,
    details: dict = None,
    request_id: str = None
) -> dict:
    """Create standardized error response"""
    error_response = {
        "success": False,
        "error": {
            "code": error_code or f"ERROR_{status_code}",
            "message": message,
            "status_code": status_code
        },
        "timestamp": logging.Formatter().formatTime(logging.LogRecord(
            name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
        )),
    }
    
    if details:
        error_response["error"]["details"] = details
    
    if request_id:
        error_response["request_id"] = request_id
    
    return error_response

def setup_error_handlers(app: FastAPI):
    """Setup global error handlers for FastAPI app"""
    
    @app.exception_handler(CustomHTTPException)
    async def custom_http_exception_handler(request: Request, exc: CustomHTTPException):
        request_id = getattr(request.state, 'request_id', None)
        
        logger.warning(f"Custom HTTP Exception: {exc.detail} (Request ID: {request_id})")
        
        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_response(
                status_code=exc.status_code,
                message=exc.detail,
                error_code=exc.error_code,
                request_id=request_id
            )
        )
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        request_id = getattr(request.state, 'request_id', None)
        
        logger.warning(f"HTTP Exception: {exc.detail} (Request ID: {request_id})")
        
        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_response(
                status_code=exc.status_code,
                message=exc.detail,
                request_id=request_id
            )
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, 'request_id', None)
        
        logger.warning(f"Validation Error: {exc.errors()} (Request ID: {request_id})")
        
        return JSONResponse(
            status_code=422,
            content=create_error_response(
                status_code=422,
                message="Validation error",
                error_code="VALIDATION_ERROR",
                details={"errors": exc.errors()},
                request_id=request_id
            )
        )
    
    @app.exception_handler(ValidationError)
    async def custom_validation_exception_handler(request: Request, exc: ValidationError):
        request_id = getattr(request.state, 'request_id', None)
        
        logger.warning(f"Custom Validation Error: {exc.message} (Request ID: {request_id})")
        
        return JSONResponse(
            status_code=400,
            content=create_error_response(
                status_code=400,
                message=exc.message,
                error_code="VALIDATION_ERROR",
                details={"field": exc.field} if exc.field else None,
                request_id=request_id
            )
        )
    
    @app.exception_handler(BusinessLogicError)
    async def business_logic_exception_handler(request: Request, exc: BusinessLogicError):
        request_id = getattr(request.state, 'request_id', None)
        
        logger.warning(f"Business Logic Error: {exc.message} (Request ID: {request_id})")
        
        return JSONResponse(
            status_code=400,
            content=create_error_response(
                status_code=400,
                message=exc.message,
                error_code=exc.error_code or "BUSINESS_LOGIC_ERROR",
                request_id=request_id
            )
        )
    
    @app.exception_handler(ExternalServiceError)
    async def external_service_exception_handler(request: Request, exc: ExternalServiceError):
        request_id = getattr(request.state, 'request_id', None)
        
        logger.error(f"External Service Error: {exc.message} (Service: {exc.service}) (Request ID: {request_id})")
        
        return JSONResponse(
            status_code=502,
            content=create_error_response(
                status_code=502,
                message="External service error",
                error_code="EXTERNAL_SERVICE_ERROR",
                details={"service": exc.service, "original_message": exc.message},
                request_id=request_id
            )
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, 'request_id', None)
        
        # Log the full exception with traceback
        logger.error(f"Unhandled Exception: {str(exc)} (Request ID: {request_id})")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        return JSONResponse(
            status_code=500,
            content=create_error_response(
                status_code=500,
                message="Internal server error",
                error_code="INTERNAL_SERVER_ERROR",
                request_id=request_id
            )
        )

    # Request ID middleware
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        import uuid
        request_id = getattr(request.state, "request_id", None) or request.headers.get("x-request-id")
        if not request_id:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Log incoming request
        logger.info(
            "Incoming request: %s %s (Request ID: %s)",
            request.method,
            request.url,
            request_id,
        )

        response = await call_next(request)

        # Log response
        logger.info(
            "Response: %s (Request ID: %s)",
            response.status_code,
            request_id,
        )

        return response

    # Detailed payload logging for style/coin flows
    @app.middleware("http")
    async def log_payloads(request: Request, call_next):
        import os
        from fastapi.responses import Response

        import uuid
        request_id = getattr(request.state, "request_id", None) or request.headers.get("x-request-id")
        if not request_id:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        path = request.url.path
        log_prefixes = (
            "/api/styles",
            "/api/v1/coins",
            "/api/v1/jobs",
            "/api/v1/webhooks/purchase",
            "/webhooks/purchase",
        )
        should_log = any(path.startswith(prefix) for prefix in log_prefixes)
        if not should_log:
            return await call_next(request)

        max_bytes = int(os.getenv("REQUEST_LOG_MAX_BYTES", "20000"))
        max_lines = int(os.getenv("REQUEST_LOG_MAX_LINES", "200"))
        pretty_lines_enabled = os.getenv("REQUEST_LOG_PRETTY_LINES", "true").lower() != "false"
        content_type = (request.headers.get("content-type") or "").lower()
        content_length = request.headers.get("content-length")
        try:
            import time
            start_time = time.perf_counter()
        except Exception:
            start_time = None

        def format_block(label: str, value: Union[dict, list, str, None]) -> str:
            try:
                if isinstance(value, (dict, list)):
                    pretty = json.dumps(value, ensure_ascii=False, indent=2)
                else:
                    pretty = str(value)
            except Exception as exc:
                pretty = f"<unserializable:{exc}>"

            lines = pretty.splitlines()
            if len(lines) > max_lines:
                pretty = "\n".join(lines[:max_lines]) + f"\n<truncated {len(lines)}/{max_lines} lines>"
            indented = "\n".join(f"    {line}" for line in pretty.splitlines())
            return f"{label}:\n{indented}"

        def get_route_info(path_value: str) -> tuple[str, str]:
            parts = [part for part in path_value.split("/") if part]
            if not parts:
                return ("root", "root")
            if parts[0] == "api" and len(parts) > 1:
                parts = parts[1:]
            if parts and parts[0].startswith("v") and len(parts) > 1:
                parts = parts[1:]
            route_value = parts[0] if parts else "root"
            endpoint_value = parts[-1] if parts else "root"
            return (route_value, endpoint_value)

        def log_payload_block(kind: str, payload: Union[dict, list, str, None], extra_fields: dict | None = None):
            if not pretty_lines_enabled or payload is None:
                return
            route_value, endpoint_value = get_route_info(request.url.path)
            header = f"[{route_value}] {kind} JSON ({endpoint_value})"
            blocks = [
                f'    request_id: "{request_id}"',
                f'    method: "{request.method}"',
                f'    path: "{request.url.path}"',
                f'    route: "{route_value}"',
                f'    endpoint: "{endpoint_value}"',
            ]
            if extra_fields:
                for key, value in extra_fields.items():
                    blocks.append(f'    {key}: "{value}"')
            blocks.append(format_block(kind.lower(), payload))
            logger.info("%s\n%s", header, "\n".join(blocks))

        body_summary = None
        if content_type.startswith("multipart/") or content_type.startswith("application/octet-stream"):
            body_summary = f"<skipped body content-type={content_type} length={content_length}>"
        else:
            try:
                raw_body = await request.body()
                # Recreate request with preserved body so downstream can read it safely.
                async def receive() -> dict:
                    return {"type": "http.request", "body": raw_body, "more_body": False}
                request = Request(request.scope, receive)
                if raw_body:
                    if content_type.startswith("application/json"):
                        try:
                            json_body = json.loads(raw_body.decode("utf-8", errors="replace"))
                            body_summary = json_body
                        except Exception:
                            body_summary = raw_body[:max_bytes].decode("utf-8", errors="replace")
                    else:
                        body_summary = raw_body[:max_bytes].decode("utf-8", errors="replace")
                    if len(raw_body) > max_bytes:
                        body_summary = {
                            "truncated": True,
                            "length": len(raw_body),
                            "preview": body_summary,
                        }
                else:
                    body_summary = None
            except Exception as exc:
                body_summary = f"<failed to read body: {exc}>"

        request_summary = {
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "query": dict(request.query_params),
            "headers": {
                "content-type": content_type,
                "content-length": content_length,
                "user-agent": request.headers.get("user-agent"),
                "x-request-id": request.headers.get("x-request-id"),
            },
            "body": body_summary,
        }
        log_payload_block("Request", request_summary)

        response = await call_next(request)

        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        response_preview = None
        try:
            if response_body:
                response_text = response_body[:max_bytes].decode("utf-8", errors="replace")
                if len(response_body) > max_bytes:
                    response_preview = {
                        "truncated": True,
                        "length": len(response_body),
                        "preview": response_text,
                    }
                else:
                    try:
                        response_preview = json.loads(response_text)
                    except Exception:
                        response_preview = response_text
        except Exception as exc:
            response_preview = f"<failed to decode response body: {exc}>"

        response_summary = {
            "status": response.status_code,
            "headers": {
                "content-type": response.headers.get("content-type"),
                "content-length": response.headers.get("content-length"),
            },
            "body": response_preview,
        }
        duration_ms = None
        if start_time is not None:
            try:
                import time
                duration_ms = int((time.perf_counter() - start_time) * 1000)
            except Exception:
                duration_ms = None
        response_extras = {
            "statusCode": response.status_code,
            "contentLength": response.headers.get("content-length"),
        }
        if duration_ms is not None:
            response_extras["durationMs"] = duration_ms
        log_payload_block("Response", response_summary, response_extras)

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=response.background,
        )

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "timestamp": logging.Formatter().formatTime(
                logging.LogRecord(
                    name="",
                    level=0,
                    pathname="",
                    lineno=0,
                    msg="",
                    args=(),
                    exc_info=None,
                )
            ),
        }

# Error logging utility
def log_error(error: Exception, context: dict = None):
    """Log error with context"""
    logger.error(f"Error: {str(error)}")
    if context:
        logger.error(f"Context: {context}")
    logger.error(f"Traceback: {traceback.format_exc()}")

def log_performance(operation: str, duration: float, metadata: dict = None):
    """Log performance metrics"""
    logger.info(f"Performance: {operation} completed in {duration:.2f}ms")
    if metadata:
        logger.info(f"Metadata: {metadata}")

def log_business_event(event: str, user_id: str = None, metadata: dict = None):
    """Log business events"""
    logger.info(f"Business Event: {event}")
    if user_id:
        logger.info(f"User ID: {user_id}")
    if metadata:
        logger.info(f"Metadata: {metadata}")





