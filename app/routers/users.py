from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.schemas.users import UserOut, UserRegister
from app.security import create_access_token, hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserRegister,
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    existing = await session.execute(select(models.User).where(models.User.login == payload.login))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Login already exists")

    # First user in the system becomes system_admin
    user_count = (await session.execute(select(func.count()).select_from(models.User))).scalar() or 0
    role_id = 1 if user_count == 0 else (payload.role_id or 2)
    user = models.User(
        login=payload.login,
        password_hash=hash_password(payload.password),
        role_id=role_id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserOut.model_validate(user)


@router.get("/me", response_model=UserOut)
async def get_me(current_user: models.User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.post("/token", response_model=dict)
async def register_and_token(
    payload: UserRegister,
    session: AsyncSession = Depends(get_session),
) -> dict:
    # helper: register + return token
    user_out = await register_user(payload, session)
    token = create_access_token({"sub": str(user_out.user_id)})
    return {"access_token": token, "token_type": "bearer", "user": user_out.model_dump()}
