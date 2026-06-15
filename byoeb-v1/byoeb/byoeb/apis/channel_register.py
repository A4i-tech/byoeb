import logging
import byoeb.chat_app.configuration.dependency_setup as dependency_setup
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

REGISTER_API_NAME = 'register_api'

register_apis_router = APIRouter()
_logger = logging.getLogger(REGISTER_API_NAME)

@register_apis_router.get("/receive")
async def register(request: Request):
    """
    Route to handle the registration process.
    """
    _logger.debug("Received the request: %s", request.query_params._dict)
    response = await dependency_setup.channel_register_handler.handle(request)
    _logger.debug("Response: %s", response.message)
    try:
        challenge = int(response.message)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid hub.challenge value")
    return JSONResponse(content=challenge, status_code=200)
    # return JSONResponse(content={"message": "received"}, status_code=200)
