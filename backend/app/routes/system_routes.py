from fastapi import APIRouter, Depends

from ..auth import AuthContext, get_auth_context, require_owner
from ..services.backups import backup_status, create_backup


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/backups")
def get_backup_status(_: AuthContext = Depends(get_auth_context)):
    return backup_status()


@router.post("/backups", status_code=201)
def run_backup(_: AuthContext = Depends(require_owner)):
    return create_backup()
