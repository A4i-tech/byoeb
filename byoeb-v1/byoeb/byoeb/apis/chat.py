import logging
import asyncio
import json
import byoeb.chat_app.configuration.dependency_setup as dependency_setup
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

CHAT_API_NAME = 'chat_api'
chat_apis_router = APIRouter()
_logger = logging.getLogger(CHAT_API_NAME)

@chat_apis_router.post("/receive")
async def receive(request: Request):
    try:
        body = await request.json()
    except Exception:
        _logger.warning("Invalid JSON in /receive")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        _logger.info("Received the request: %s", json.dumps(body))
    except Exception:
        _logger.info("Received the request (non-serializable body logged as str)")

    try:
        resp = await dependency_setup.message_producer_handler.handle(body)
    except Exception as e:
        _logger.exception("Unhandled error in message_producer_handler.handle")
        safe_err = {"ok": False, "error_type": type(e).__name__, "error": str(e)}
        return JSONResponse(content=safe_err, status_code=500)

    payload = getattr(resp, "message", None)
    safe = jsonable_encoder(
        payload,
        custom_encoder={
            Exception: lambda e: {"type": e.__class__.__name__, "message": str(e)}
        },
    )

    return JSONResponse(content=safe, status_code=int(getattr(resp, "status_code", 200)))

@chat_apis_router.get("/get_bot_messages")
async def get_bot_messages(
    request: Request, 
    timestamp: str = Query(..., description="Unix timestamp as a string")
):
    """
    Get all messages for a specific BO.
    """
    responses = await dependency_setup.message_db_service.get_latest_bot_messages_by_timestamp(timestamp)
    byoeb_response = []
    for response in responses:
        byoeb_response.append(response.model_dump())
    return JSONResponse(
        content=byoeb_response,
        status_code=200
    )

@chat_apis_router.delete("/delete_message_collection")
async def delete_collection(
    request: Request,
):
    """
    Delete a collection from the database.
    """
    response, e = await dependency_setup.message_db_service.delete_message_collection()
    if response == True:
        return JSONResponse(
            content="Successfully deleted",
            status_code=200
        )
    elif response == False and e is None:
        return JSONResponse(
            content="Failed to delete",
            status_code=500
        )
    elif e is not None:
        return JSONResponse(
            content=f"Error: {e}",
            status_code=500
        )
