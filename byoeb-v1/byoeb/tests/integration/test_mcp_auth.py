import pytest
from fastmcp import Client
from mcp.types import TextContent

@pytest.mark.asyncio
async def test_mcp_oauth_health_and_chat(envs, auth_access_token, auth_me):
    if not auth_me.phone_number_id:
        pytest.skip("phone_number_id missing on /auth/me")

    async with Client(f"{envs.base_url}/mcp", auth=auth_access_token) as client:
        result = await client.call_tool("asha_service_health", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Chat bot is running"

        result = await client.call_tool("asha_chat", {"message": "hello"})
        assert result.structured_content is not None
        assert "category" in result.structured_content
        assert "text" in result.structured_content
