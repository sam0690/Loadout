import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class ArchetypeOut(BaseModel):
    slug: str
    name: str
    equipment: list[str]


class Loads(BaseModel):
    """A context's own answer for one piece of equipment (D21). Absent means the catalog
    default stands, which is not the same as 'not loadable'."""

    load_increments: list[Decimal] | None = None
    bar_weight: Decimal | None = None


class ContextIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    archetype_slug: str | None = None
    equipment_added: list[str] = []
    equipment_removed: list[str] = []
    is_default: bool = False
    loads: dict[str, Loads] = {}


class ResolvedEquipment(BaseModel):
    slug: str
    equipment_class: str
    is_fixed_path: bool
    load_increments: list[Decimal] | None
    bar_weight: Decimal | None


class ContextOut(BaseModel):
    id: uuid.UUID
    label: str
    archetype_slug: str | None
    is_default: bool
    equipment: list[ResolvedEquipment]
