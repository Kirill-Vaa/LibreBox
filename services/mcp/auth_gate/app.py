import asyncio
import hashlib
from typing import Final

import jwt
from bson import ObjectId
from bson.errors import InvalidId
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from auth_gate.constants import AUTH_HEALTH_TIMEOUT_SECONDS
from auth_gate.session_store import SessionStore, SessionStoreUnavailableError
from utils.logger import logger


_AUTH_COOKIE_NAME: Final[str] = "refreshToken"


class AuthGate:
    def __init__(self, session_store: SessionStore, jwt_refresh_secret: str) -> None:
        self._session_store = session_store
        self._jwt_refresh_secret = jwt_refresh_secret

    async def check_session_store(self) -> None:
        async with asyncio.timeout(AUTH_HEALTH_TIMEOUT_SECONDS):
            await self._session_store.ping()

    async def authenticate(self, cookie_header: str) -> str | None:
        refresh_token = self._extract_refresh_token(cookie_header)
        if refresh_token is None:
            return None

        user_id = self._decode_user_id(refresh_token)
        if user_id is None:
            return None

        try:
            user_object_id = ObjectId(user_id)
        except InvalidId:
            logger.warning(f"Rejected refresh token with a malformed user id user={user_id}")
            return None

        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        if not await self._session_store.is_session_live(user_object_id, token_hash):
            logger.info(f"Rejected refresh token without a live LibreChat session user={user_id}")
            return None

        return user_id

    def _decode_user_id(self, refresh_token: str) -> str | None:
        try:
            payload = jwt.decode(refresh_token, self._jwt_refresh_secret, algorithms=["HS256"], options={"require": ["exp"]})
        except jwt.PyJWTError as error:
            logger.debug(f"Rejected refresh token error={error}")
            return None

        user_id = payload.get("id")
        return str(user_id) if user_id is not None else None

    @staticmethod
    def _extract_refresh_token(cookie_header: str) -> str | None:
        for cookie_pair in cookie_header.split(";"):
            name, separator, value = cookie_pair.partition("=")
            if not separator or name.strip() != _AUTH_COOKIE_NAME:
                continue

            token = value.strip()
            if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
                token = token[1:-1]

            return token or None

        return None


def create_auth_app(auth_gate: AuthGate) -> Starlette:
    async def healthz(request: Request) -> JSONResponse:
        try:
            await auth_gate.check_session_store()
        except (SessionStoreUnavailableError, TimeoutError) as error:
            logger.warning(f"Auth gate health probe failed: {error}")
            return JSONResponse({"status": "unavailable", "dependency": "mongodb"}, status_code=503, headers={"Retry-After": "5"})

        return JSONResponse({"status": "ok"})

    async def validate(request: Request) -> Response:
        try:
            user_id = await auth_gate.authenticate(request.headers.get("cookie", ""))
        except SessionStoreUnavailableError:
            return Response(status_code=503, headers={"Retry-After": "5"})

        if user_id is None:
            return Response(status_code=401)

        return Response(headers={"X-Auth-User": user_id})

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/auth/validate", validate, methods=["GET"]),
        ]
    )
