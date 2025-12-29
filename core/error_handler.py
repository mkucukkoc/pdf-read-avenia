import logging
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










