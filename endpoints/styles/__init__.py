from .video import router as video_router
from .city import router as city_router
from .car import router as car_router
from .family import router as family_router
from .history import router as history_router

__all__ = ["video_router", "city_router", "car_router", "family_router", "history_router"]
