import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse

HEALTH_API_NAME = 'health_api'

health_apis_router = APIRouter()
_logger = logging.getLogger(HEALTH_API_NAME)

@health_apis_router.get("/")
async def webhook():
    """
    Health check route to confirm the app is running.
    """
    _logger.debug("Request for index page received")
    return JSONResponse(content={"detail": "App is running"}, status_code=200)

def health_mcps_router(mcp):
    @mcp.tool
    def asha_service_health():
        """
        Health check route to confirm the app is running.
        """
        return "App is running"
