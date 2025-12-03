import logging
import json
from byoeb.kb_app.configuration.dependency_setup import amedia_storage
from byoeb.services.knowledge_base.kb_service import upload as kb_upload
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

KB_API_NAME = 'kb_api'

kb_apis_router = APIRouter()
_logger = logging.getLogger(KB_API_NAME)

@kb_apis_router.get("/load")
async def load_from_blob_store(request: Request):
    _logger.info("🚀 Starting knowledge base load from blob store")
    try:
        files = await amedia_storage.aget_all_files_properties()
        count = await kb_upload(files)
        _logger.info(f"✅ Successfully loaded {count} documents into knowledge base")
        return JSONResponse(
            content={"message": f"Loaded {count} documents"},
            status_code=200
        )
    except Exception as e:
        _logger.error(f"❌ Error loading knowledge base: {str(e)}", exc_info=True)
        return JSONResponse(
            content={"error": str(e), "message": "Failed to load knowledge base"},
            status_code=500
        )

# @kb_apis_router.post("/add_document")
# async def add_document(request: Request):
#     body = await request.json()
#     response = await dependency_setup.users_handler.aregister(body)
#     print("Response: ", response.message)
#     return JSONResponse(
#         content=response.message,
#         status_code=response.status_code
#     )

# @kb_apis_router.delete("/delete_document")
# async def delete_document(request: Request):
#     body = await request.json()
#     response = await dependency_setup.users_handler.adelete(body)
#     return JSONResponse(
#         content=response.message,
#         status_code=response.status_code
#     )

# @kb_apis_router.post("/replace_document")
# async def replace_document(request: Request):
#     body = await request.json()
#     response = await dependency_setup.users_handler.aget(body)
#     return JSONResponse(
#         content=response.message,
#         status_code=response.status_code
#     )