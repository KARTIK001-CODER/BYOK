from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.organizations import OrganizationResponse
from app.schemas.users import UserResponse
from app.services.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Registers a new user, provisions default organization, and issues JWT tokens.",
)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_db),
) -> AuthResponse:
    user, org, access_token, refresh_token, expires_in = await AuthService.register(
        session=session,
        payload=payload,
    )
    return AuthResponse(
        user=UserResponse.model_validate(user),
        organization=OrganizationResponse.model_validate(org),
        tokens=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=expires_in,
        ),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="User Login",
    description="Authenticates credentials and returns an access token and rotating refresh token.",
)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    _, access_token, refresh_token, expires_in = await AuthService.login(
        session=session,
        payload=payload,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh Access Token",
    description="Rotates refresh token and issues new access token with reuse detection.",
)
async def refresh_token(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    access_token, new_refresh_token, expires_in = await AuthService.refresh_tokens(
        session=session,
        raw_refresh_token=payload.refresh_token,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout User",
    description="Revokes the provided refresh token. Operation is idempotent.",
)
async def logout(
    payload: LogoutRequest,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await AuthService.logout(
        session=session,
        raw_refresh_token=payload.refresh_token,
    )
    return {"message": "Successfully logged out."}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Current User Profile",
    description="Returns public profile information for authenticated user without secrets.",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)
