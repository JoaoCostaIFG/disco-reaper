"""Fluxer platform integration.

Applies runtime compatibility patches to the fluxer.py library (0.4.2),
which is required for sticker support against self-hosted Fluxer instances.
"""

import base64
import logging
from typing import Any

from fluxer.http import HTTPClient

logger = logging.getLogger(__name__)


def _apply_fluxer_compat_patches() -> None:
    """Fix upstream fluxer.py sticker endpoints for custom api_url instances.

    The sticker methods in fluxer.py 0.4.2 build Route objects directly
    instead of via HTTPClient._route, so they always target the default
    https://api.fluxer.app/v1 base URL instead of the client's configured
    api_url. Every sticker request against a self-hosted instance therefore
    fails with 401 Unauthorized (the bot token is not valid on the public
    API). delete_guild_sticker additionally has a "{stickers_id}" template
    typo that raises KeyError before any request is made.

    Upstream: https://github.com/Fluxer-py/fluxer.py (unfixed as of 0.4.2)
    """
    if getattr(HTTPClient.get_guild_stickers, "_reaper_patched", False):
        return

    async def get_guild_stickers(self, guild_id: int | str) -> list[dict[str, Any]]:
        return await self.request(
            self._route("GET", "/guilds/{guild_id}/stickers", guild_id=guild_id)
        )

    async def get_guild_sticker(
        self, guild_id: int | str, sticker_id: int | str
    ) -> dict[str, Any]:
        return await self.request(
            self._route(
                "GET",
                "/guilds/{guild_id}/sticker/{sticker_id}",
                guild_id=guild_id,
                sticker_id=sticker_id,
            )
        )

    async def create_guild_sticker(
        self,
        guild_id: int | str,
        *,
        name: str,
        image: bytes,
        roles: list[int | str] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        image_data = base64.b64encode(image).decode("ascii")

        if image.startswith(b"\x89PNG"):
            mime_type = "image/png"
        elif image.startswith(b"\xff\xd8\xff"):
            mime_type = "image/jpeg"
        elif image.startswith(b"GIF89a") or image.startswith(b"GIF87a"):
            mime_type = "image/gif"
        else:
            mime_type = "image/png"

        payload: dict[str, Any] = {
            "name": name,
            "image": f"data:{mime_type};base64,{image_data}",
        }
        if roles is not None:
            payload["roles"] = [str(role_id) for role_id in roles]

        return await self.request(
            self._route("POST", "/guilds/{guild_id}/stickers", guild_id=guild_id),
            json=payload,
            reason=reason,
        )

    async def delete_guild_sticker(
        self,
        guild_id: int | str,
        sticker_id: int | str,
        *,
        reason: str | None = None,
    ) -> None:
        await self.request(
            self._route(
                "DELETE",
                "/guilds/{guild_id}/stickers/{sticker_id}",
                guild_id=guild_id,
                sticker_id=sticker_id,
            ),
            reason=reason,
        )

    for name, method in (
        ("get_guild_stickers", get_guild_stickers),
        ("get_guild_sticker", get_guild_sticker),
        ("create_guild_sticker", create_guild_sticker),
        ("delete_guild_sticker", delete_guild_sticker),
    ):
        method._reaper_patched = True
        setattr(HTTPClient, name, method)

    logger.debug("Applied fluxer.py sticker endpoint compat patches")


_apply_fluxer_compat_patches()
