from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import AppSession
from app.auth import service
from app.auth.middleware import _token
from app.auth.passwords import verify_password
from app.domain.models import AdminUser

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1, max_length=1024)
    """No complexity rules: the only requirement is that it is not empty."""


class Me(BaseModel):
    username: str
    must_change_password: bool


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        service.SESSION_COOKIE,
        token,
        max_age=service.SESSION_HOURS * 3600,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _current(request: Request, session: AppSession) -> AdminUser:
    token = _token(request.scope)
    user = await service.user_for_token(session, token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


@router.post("/login", response_model=Me)
async def login(payload: LoginRequest, request: Request, response: Response, session: AppSession) -> Me:
    client = _client(request)
    if await service.is_locked(session, client):
        raise HTTPException(status_code=429, detail="Too many failed attempts; try again in a minute")
    user = await service.authenticate(session, payload.username, payload.password)
    if user is None:
        await service.record_failure(session, client)
        raise HTTPException(status_code=401, detail="Wrong username or password")
    await service.clear_failures(session, client)
    _set_cookie(request, response, await service.create_session(session))
    return Me(username=user.username, must_change_password=user.must_change_password)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, session: AppSession) -> None:
    token = _token(request.scope)
    if token:
        await service.end_session(session, token)
    response.delete_cookie(service.SESSION_COOKIE, path="/")


@router.get("/me", response_model=Me)
async def me(request: Request, session: AppSession) -> Me:
    user = await _current(request, session)
    return Me(username=user.username, must_change_password=user.must_change_password)


@router.post("/password", response_model=Me)
async def change_password(
    payload: PasswordChange, request: Request, response: Response, session: AppSession
) -> Me:
    user = await _current(request, session)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    _set_cookie(request, response, await service.change_password(session, user, payload.new_password))
    return Me(username=user.username, must_change_password=False)
