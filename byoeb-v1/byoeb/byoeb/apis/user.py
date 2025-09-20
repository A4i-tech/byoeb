import logging
import json
import random
import byoeb.chat_app.configuration.dependency_setup as dependency_setup
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastmcp import Context
from pydantic import BaseModel, Field
from typing import Literal

USER_API_NAME = 'user_api'

user_apis_router = APIRouter()
_logger = logging.getLogger(USER_API_NAME)

@user_apis_router.post("/register_users")
async def register_users(request: Request):
    body = await request.json()
    response = await dependency_setup.users_handler.aregister(body)
    print("Response: ", response.message)
    return JSONResponse(
        content=response.message,
        status_code=response.status_code
    )

@user_apis_router.post("/update_users")
async def update_users():
    return JSONResponse(content={"message": "received"}, status_code=200)

@user_apis_router.delete("/delete_users")
async def delete_users(request: Request):
    body = await request.json()
    response = await dependency_setup.users_handler.adelete(body)
    return JSONResponse(
        content=response.message,
        status_code=response.status_code
    )

@user_apis_router.get("/get_users")
async def get_users(request: Request):
    body = await request.json()
    response = await dependency_setup.users_handler.aget(body)
    return JSONResponse(
        content=response.message,
        status_code=response.status_code
    )

def user_mcps_router(mcp):
    class UserInput(BaseModel):
        name: str = Field(..., min_length=3, max_length=100)
        phone_number: str = Field(..., description="10 digit phone number")
        language: Literal["en", "hi", "mr", "te"] = Field(..., description="Supported language codes")
        state: str = Field(..., description="Name of a state in India")

    @mcp.tool
    async def register_asha_user(ctx: Context):
        """
        Register a new Asha user.
        """
        response = await ctx.elicit("Please provide user information", response_type=UserInput)
        if response.action != "accept":
            return "User creation aborted"

        response = await dependency_setup.users_handler.aregister([dict(
            user_id=str(random.randint(10000, 99999)),
            user_name=response.data.name,
            user_location=dict(country="IN", region=response.data.state),
            user_language=response.data.language,
            user_type="asha",
            phone_number_id=response.data.phone_number
        )])
        return response