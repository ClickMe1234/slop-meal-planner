from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth_context, require_owner
from ..config import get_settings
from ..db import get_db
from ..errors import DomainError
from ..models import UserRole
from ..schemas import IntegrationCredentialUpdate
from ..services.backups import backup_status, create_backup
from ..services.integration_credentials import (
    USDA_PROVIDER,
    delete_credential,
    effective_usda_key,
    save_credential,
)


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/backups")
def get_backup_status(_: AuthContext = Depends(get_auth_context)):
    return backup_status()


@router.post("/backups", status_code=201)
def run_backup(_: AuthContext = Depends(require_owner)):
    return create_backup()


@router.get("/integrations/usda")
def get_usda_integration(
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    if context.user.role != UserRole.OWNER.value:
        raise DomainError("OWNER_REQUIRED", "Owner access is required", 403)
    _, source = effective_usda_key(db, context.user.household_id, get_settings())
    return {
        "configured": source in {"saved", "environment"},
        "source": source,
        "signup_url": "https://fdc.nal.usda.gov/api-key-signup.html",
    }


@router.put("/integrations/usda")
def put_usda_integration(
    payload: IntegrationCredentialUpdate,
    context: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    save_credential(
        db,
        context.user.household_id,
        USDA_PROVIDER,
        payload.api_key.strip(),
        get_settings(),
    )
    return {"configured": True, "source": "saved", "signup_url": "https://fdc.nal.usda.gov/api-key-signup.html"}


@router.delete("/integrations/usda", status_code=204)
def remove_usda_integration(
    context: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    delete_credential(db, context.user.household_id, USDA_PROVIDER)
    return Response(status_code=204)
