from fastapi import APIRouter

from app.schemas.user import UserOut
from app.security import CurrentUser

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user
