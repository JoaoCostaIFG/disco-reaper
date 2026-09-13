import base64
import pytest
from unittest.mock import AsyncMock

import src.fluxer  # noqa: F401 - applies the fluxer.py compat patches on import
from fluxer.http import HTTPClient

CUSTOM_API_URL = "https://chat.example.com/api/v1"
GUILD_ID = "1548786628749688832"


@pytest.fixture
def http_client():
    client = HTTPClient("fake_token", api_url=CUSTOM_API_URL)
    client.request = AsyncMock(return_value=[])
    return client


async def _captured_route(client):
    route = client.request.await_args.args[0]
    return route


@pytest.mark.asyncio
async def test_get_guild_stickers_uses_custom_api_url(http_client):
    await http_client.get_guild_stickers(GUILD_ID)
    route = await _captured_route(http_client)
    assert route.url == f"{CUSTOM_API_URL}/guilds/{GUILD_ID}/stickers"


@pytest.mark.asyncio
async def test_get_guild_sticker_uses_custom_api_url(http_client):
    http_client.request.return_value = {}
    await http_client.get_guild_sticker(GUILD_ID, "42")
    route = await _captured_route(http_client)
    assert route.url == f"{CUSTOM_API_URL}/guilds/{GUILD_ID}/sticker/42"


@pytest.mark.asyncio
async def test_create_guild_sticker_uses_custom_api_url(http_client):
    png_bytes = b"\x89PNG" + b"0" * 10
    http_client.request.return_value = {"id": "1", "name": "test"}
    await http_client.create_guild_sticker(GUILD_ID, name="test", image=png_bytes)
    route, kwargs = http_client.request.await_args.args[0], http_client.request.await_args.kwargs
    assert route.url == f"{CUSTOM_API_URL}/guilds/{GUILD_ID}/stickers"
    expected_b64 = base64.b64encode(png_bytes).decode("ascii")
    assert kwargs["json"]["image"] == f"data:image/png;base64,{expected_b64}"
    assert kwargs["json"]["name"] == "test"


@pytest.mark.asyncio
async def test_delete_guild_sticker_uses_custom_api_url(http_client):
    await http_client.delete_guild_sticker(GUILD_ID, "42")
    route = await _captured_route(http_client)
    assert route.url == f"{CUSTOM_API_URL}/guilds/{GUILD_ID}/stickers/42"


@pytest.mark.asyncio
async def test_emoji_endpoints_still_use_custom_api_url(http_client):
    await http_client.get_guild_emojis(GUILD_ID)
    route = await _captured_route(http_client)
    assert route.url == f"{CUSTOM_API_URL}/guilds/{GUILD_ID}/emojis"
