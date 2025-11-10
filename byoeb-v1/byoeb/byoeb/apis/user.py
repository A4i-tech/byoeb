import logging
from typing import Any, List, Optional, Dict
from byoeb_core.models.byoeb.user import User
from fastapi import APIRouter, Body, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from byoeb_core.models.byoeb.response import ByoebStatusCodes
import byoeb.chat_app.configuration.dependency_setup as dependency_setup
from byoeb.constants.user_enums import LanguageCode, UserType
from byoeb.services.user.utils import get_user_ids_from_phone_number_ids
from byoeb.utils.utils import mcp_get_phone_number

USER_API_NAME = "user_api"
_logger = logging.getLogger(USER_API_NAME)

user_apis_router = APIRouter(tags=["Users"])


# -----------------------------
# Pydantic models
# -----------------------------

class UserLocation(BaseModel):
    district: str = Field(..., description="District name (required)", json_schema_extra="Jaipur")
    block: Optional[str] = Field(None, description="Block name", json_schema_extra="Sanganer")
    sector: Optional[str] = Field(None, description="Sector name", json_schema_extra="Sector 12")
    sub_center: Optional[str] = Field(None, description="Sub-center name", json_schema_extra="SC-45")

   

class APIResponse(BaseModel):
    status: str = Field(..., description="Response status — 'success' or 'error'", json_schema_extra="success")
    message: str = Field(..., description="Human-readable message", json_schema_extra="User registered successfully.")
    content: Optional[Any] = Field(None, description="Payload or additional data")


class UserRegister(BaseModel):
    phone_number_id: str = Field(..., description="Phone number ID of the user", json_schema_extra="9982674531")
    user_location: Optional[UserLocation] = Field(..., description="Location details (district is mandatory)")
    user_type: str = Field(..., description="Type of user (asha, anm, etc.)", json_schema_extra="asha")
    user_language: str = Field(..., description="Language code (hi, en, te, etc.)", json_schema_extra="hi")
    user_name: Optional[str] = Field(None, description="Name of the user", json_schema_extra="Sita Devi")
    test_user: Optional[bool] = Field(False, description="Flag to mark test users", json_schema_extra=True)



class UserUpdate(BaseModel):
    phone_number_id: str = Field(..., description="Phone number ID of the user", json_schema_extra="9982674531")
    user_name: Optional[str] = Field(None, description="Updated name of the user", json_schema_extra="John Doe")
    user_location: Optional[Dict[str, Any]] = Field(None, description="Updated location details")
    user_language: Optional[str] = Field(None, description="Updated language code", json_schema_extra="en")
    user_type: Optional[str] = Field(None, description="Updated type of user", json_schema_extra="anm")
    user_name: Optional[str] = Field(None, description="Name of the user", json_schema_extra="Sita Devi")
    test_user: Optional[bool] = Field(None, description="Flag to mark test users", json_schema_extra=False)



class User_Phone(BaseModel):
    phone_number_id: str = Field(..., description="Phone number ID of the user", json_schema_extra="9982674531")


# -----------------------------
# Endpoints
# -----------------------------

@user_apis_router.post(
    "/register_users",
    summary="Register one or more users",)
async def register_users(
    users: List[UserRegister] = Body(
        ...,
        description="List of users to register. Mandatory fields: `user_type`, `user_location` and `phone_number_id`. `district` inside `user_location` is mandatory.",
        examples={
            "full_example": {
                "summary": "Full user location with optional fields",
                "value": [
                    {
                        "phone_number_id": "9982674531",
                        "user_location": {
                            "district": "Jaipur",
                            "block": "Sanganer",
                            "sector": "Sector 12",
                            "sub_center": "SC-45",
                        },
                        "user_type": "asha",
                        "user_language": "hi",
                        "test_user": True,
                    }
                ],
            },
        },
    ),
) -> List[User]:
    """
    Registers one or more users.

    - `district` inside `user_location` is **mandatory**.
    - Other fields like `block`, `sector`, `sub_center` are optional.
    - Calls the async handler `users_handler.aregister` with validated payload.
    """
    payload = [u.dict(exclude_unset=True) for u in users]
    response = await dependency_setup.users_handler.aregister(payload)
    if response.status_code == ByoebStatusCodes.OK.value:
        return [User(**x) for x in response.message]

    return JSONResponse(content=response.message, status_code=response.status_code)


@user_apis_router.post(
    "/update_users",
    summary="Update one or more users",
    response_model=APIResponse,
)
async def update_users(
    users: List[UserUpdate] = Body(
        ...,
        description="List of users to update. Only include fields that need updating.",
        examples={
            "example": {
                "summary": "User update example",
                "value": [
                    {
                        "phone_number_id": "9982674531",
                        "user_language": "mr",
                    }
                ],
            },
        },
    ),
) -> APIResponse:
    """
    Update one or more users.

    - `phone_number_id` is **mandatory**.
    - Include only fields that need to be updated.
    - Calls `users_handler.aupdate` internally.
    """
    try:
        payload = [u.dict(exclude_unset=True) for u in users]
        response = await dependency_setup.users_handler.aupdate(payload)

        return JSONResponse(
            content=response.message,
            status_code=response.status_code
        )

    except Exception as e:
        _logger.exception(f"Error in /update_users: {str(e)}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )
       
@user_apis_router.delete(
    "/delete_users",
    summary="Delete one or more users",
    response_model=APIResponse,
)
async def delete_users(users: List[str] = Body(
        ...,
        description="List of phone_number_ids (must be numeric).",
        json_schema_extra=["9982674531", "9876543210"]    )) -> APIResponse:
    """
    Deletes users matching the provided phone_number_ids.
    """
    try:
        response = await dependency_setup.users_handler.adelete(users)

        return APIResponse(
            status="success" if 200 <= response.status_code < 300 else "error",
            message=response.message if isinstance(response.message, str) else str(response.message),
        )

    except Exception as e:
        _logger.exception(f"Error in /delete_users: {str(e)}")
        return APIResponse(status="error", message=str(e))

@user_apis_router.get(
    "/get_users",
    summary="Retrieve one or more users by phone_number_id",
    tags=["Users"],
)
async def get_users(
    phone_number_ids: List[str] = Body(
        ...,
        description="List of phone_number_ids (must be numeric).",
        json_schema_extra=["9982674531", "9876543210"]    )
) -> List[User]:
    """
    Retrieve user information for one or more users.
    - Accepts multiple `phone_number_id` values as query parameters.
    """
    response = await dependency_setup.users_handler.aget(phone_number_ids)
    print("Response from aget:", response.message)

    return list(map(lambda x: User(**x), response.message))

    

# -----------------------------
# MCP Tool Registration
# -----------------------------

def user_mcps_router(mcp):
    class UserInput(BaseModel):
        name: str = Field(..., min_length=3, max_length=100)
        language: LanguageCode = Field(..., description="Supported language codes")
        state: str = Field(..., description="Name of a state in India")

    @mcp.tool
    async def asha_register_user(data: UserInput):
        """
        Register a new Asha user.
        """
        phone_number = mcp_get_phone_number()
        response = await dependency_setup.users_handler.aregister([
            dict(
                user_id=get_user_ids_from_phone_number_ids([phone_number])[0],
                user_name=data.name,
                user_location=dict(country="IN", region=data.state),
                user_language=data.language.value,
                user_type=UserType.ASHA.value,
                phone_number_id=phone_number,
            )
        ])
        return response