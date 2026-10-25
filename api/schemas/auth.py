import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

from engine.generator import Experience, Goal


class RequestLink(BaseModel):
    email: EmailStr


class Credentials(BaseModel):
    email: EmailStr
    # The ceiling stops a megabyte "password" from buying a megabyte of scrypt work.
    password: str = Field(min_length=8, max_length=256)


class Verify(BaseModel):
    token: str


class Session(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class Me(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime


class Profile(BaseModel):
    """The intake answers. Every field optional, in both directions.

    Bounds mirror the CHECK constraints in schema.py rather than trusting them: a 422 at
    the boundary names the offending field, a constraint violation is a 500 that does not.
    They are typo rails and nothing more.
    """

    # Stripped first, so "  " is a 422 rather than a blank name on the profile.
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)
    ] | None = None
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    height_cm: int | None = Field(default=None, ge=50, le=280)
    bodyweight_kg: Decimal | None = Field(default=None, ge=20, le=500, decimal_places=2)
    goal: Goal | None = None
    experience: Experience | None = None
    days_per_week: int | None = Field(default=None, ge=1, le=7)
    session_minutes: int | None = Field(default=None, ge=10, le=300)


PROFILE_FIELDS = tuple(Profile.model_fields)
