from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from typing import Optional

from .. import schemas
from .. import database
from ..database import get_db
from ..llm_gateway import LLMGateway

router = APIRouter(prefix="/settings", tags=["settings"])


def _get_or_create_settings(db: Session) -> database.AppSettings:
    row = db.query(database.AppSettings).filter(database.AppSettings.id == 1).first()
    if not row:
        row = database.AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("/", response_model=schemas.AppSettings)
def get_settings(db: Session = Depends(get_db)):
    row = _get_or_create_settings(db)
    return schemas.AppSettings(
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        llm_api_key=None,                        # never expose
        llm_base_url=row.llm_base_url,
        llm_temperature=row.llm_temperature,
        llm_custom_rules=row.llm_custom_rules,
        has_api_key=bool(row.llm_api_key),
    )


@router.put("/", response_model=schemas.AppSettings)
def update_settings(body: schemas.AppSettings, request: Request, db: Session = Depends(get_db)):
    row = _get_or_create_settings(db)

    if body.llm_provider is not None:
        row.llm_provider = body.llm_provider
    if body.llm_model is not None:
        row.llm_model = body.llm_model
    # Only update api_key if a non-empty value was sent
    if body.llm_api_key:
        row.llm_api_key = body.llm_api_key
    if body.llm_base_url is not None:
        row.llm_base_url = body.llm_base_url
    if body.llm_temperature is not None:
        row.llm_temperature = body.llm_temperature
    if body.llm_custom_rules is not None:
        row.llm_custom_rules = body.llm_custom_rules

    db.commit()
    db.refresh(row)

    # Reinitialize LLM gateway with new settings
    gw = LLMGateway(
        provider=row.llm_provider or "ollama",
        api_key=row.llm_api_key,
        base_url=row.llm_base_url,
        model=row.llm_model or "llama3",
        temperature=row.llm_temperature or 0.7,
    )
    gw.custom_rules = row.llm_custom_rules or ""
    request.app.state.llm_gateway = gw

    return schemas.AppSettings(
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        llm_api_key=None,
        llm_base_url=row.llm_base_url,
        llm_temperature=row.llm_temperature,
        llm_custom_rules=row.llm_custom_rules,
        has_api_key=bool(row.llm_api_key),
    )
