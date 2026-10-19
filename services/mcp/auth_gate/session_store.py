import time
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from auth_gate.constants import AUTH_MONGO_TIMEOUT_MS, AUTH_SESSION_CACHE_MAX_ENTRIES, AUTH_SESSION_CACHE_TTL_SECONDS, LIBRECHAT_SESSIONS_COLLECTION
from utils.logger import logger


class SessionStoreUnavailableError(Exception):
    pass


class SessionStore:
    def __init__(self, mongo_uri: str, database_name: str) -> None:
        self._client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=AUTH_MONGO_TIMEOUT_MS,
            connectTimeoutMS=AUTH_MONGO_TIMEOUT_MS,
            socketTimeoutMS=AUTH_MONGO_TIMEOUT_MS,
        )
        self._sessions = self._client[database_name][LIBRECHAT_SESSIONS_COLLECTION]
        self._live_session_cache: OrderedDict[tuple[ObjectId, str], float] = OrderedDict()

    async def close(self) -> None:
        await self._client.close()

    async def ping(self) -> None:
        try:
            await self._client.admin.command("ping")
        except PyMongoError as error:
            logger.warning(f"Session store ping failed: {error}")
            raise SessionStoreUnavailableError(str(error)) from error

    async def is_session_live(self, user_id: ObjectId, refresh_token_hash: str) -> bool:
        cache_key = (user_id, refresh_token_hash)
        now = time.monotonic()
        cached_until = self._live_session_cache.get(cache_key)
        if cached_until is not None and cached_until > now:
            return True

        self._live_session_cache.pop(cache_key, None)
        query = {"user": user_id, "refreshTokenHash": refresh_token_hash, "expiration": {"$gt": datetime.now(UTC)}}

        try:
            is_live = await self._sessions.find_one(query, projection={"_id": 1}) is not None
        except PyMongoError as error:
            logger.error(f"Failed to look up the LibreChat session for user {user_id}: {error}")
            raise SessionStoreUnavailableError(str(error)) from error

        if is_live:
            self._live_session_cache[cache_key] = now + AUTH_SESSION_CACHE_TTL_SECONDS
            if len(self._live_session_cache) > AUTH_SESSION_CACHE_MAX_ENTRIES:
                self._live_session_cache.popitem(last=False)

        return is_live
