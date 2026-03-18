from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.schemas.users import UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(current_user: models.User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)
