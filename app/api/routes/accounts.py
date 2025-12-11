from typing import List, Optional
from fastapi import APIRouter, Depends, status
from ...services import db
from ...schemas.accounts import AccountBase, AccountCreate, AccountOut
from ...core.auth import verify_supabase_token

router = APIRouter(
    prefix="/accounts",
    tags=["accounts"]
)

@router.get("/", response_model=List[AccountOut])
def list_accounts(
    user_id: str = Depends(verify_supabase_token),
):
    rows = db.get_user_accounts(user_id=user_id)
    return [AccountOut(**row) for row in rows]


@router.post(
    "/",
    response_model=AccountOut,
    status_code=status.HTTP_201_CREATED,
)
def create_account(
    body: AccountCreate,
    user_id: str = Depends(verify_supabase_token),
):
    row = db.create_user_account(
        user_id=user_id,
        account_data=body.model_dump(),
    )
    return AccountOut(**row)