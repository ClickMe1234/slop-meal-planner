from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import IntegrationCredential


USDA_PROVIDER = "usda_food_data_central"


def _fernet(settings: Settings) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt_value(value: str, settings: Settings) -> str:
    return _fernet(settings).encrypt(value.encode()).decode()


def decrypt_value(value: str, settings: Settings) -> str:
    return _fernet(settings).decrypt(value.encode()).decode()


def credential_for(db: Session, household_id: str, provider: str) -> IntegrationCredential | None:
    return db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.household_id == household_id,
            IntegrationCredential.provider == provider,
        )
    )


def save_credential(db: Session, household_id: str, provider: str, value: str, settings: Settings) -> None:
    encrypted = encrypt_value(value, settings)
    credential = credential_for(db, household_id, provider)
    if credential is None:
        credential = IntegrationCredential(
            household_id=household_id,
            provider=provider,
            encrypted_value=encrypted,
        )
        db.add(credential)
    else:
        credential.encrypted_value = encrypted
        credential.version += 1
    db.commit()


def delete_credential(db: Session, household_id: str, provider: str) -> None:
    credential = credential_for(db, household_id, provider)
    if credential is not None:
        db.delete(credential)
        db.commit()


def effective_usda_key(db: Session, household_id: str, settings: Settings) -> tuple[str, str]:
    credential = credential_for(db, household_id, USDA_PROVIDER)
    if credential is not None:
        try:
            return decrypt_value(credential.encrypted_value, settings), "saved"
        except InvalidToken:
            return "", "invalid"
    environment_key = settings.usda_api_key.strip()
    if environment_key and environment_key != "DEMO_KEY":
        return environment_key, "environment"
    if environment_key == "DEMO_KEY":
        return environment_key, "demo"
    return "", "missing"
