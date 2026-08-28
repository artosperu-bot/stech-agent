from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    READ = "READ"
    EXPORT = "EXPORT"
    COMPARE = "COMPARE"
    UPDATE_FIELDS = "UPDATE_FIELDS"
    PREPARE_CHANGESET = "PREPARE_CHANGESET"
    APPLY_CHANGESET = "APPLY_CHANGESET"
    GENERATE_SEO = "GENERATE_SEO"
    UPLOAD_SEO = "UPLOAD_SEO"
    CREATE_PRODUCT = "CREATE_PRODUCT"


class TaskState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RiskLevel(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


@dataclass(frozen=True, slots=True)
class ProductRecord:
    sku: str
    name: str = ""
    description: str = ""
    category: str = ""
    subcategory: str = ""
    brand: str = ""
    price: Decimal | None = None
    discount: Decimal | None = None
    stock: int | None = None
    is_new: bool | None = None
    on_offer: bool | None = None
    recommended: bool | None = None
    featured: bool | None = None
    visible: bool | None = None
    status: str = ""
    main_specs: str = ""
    technical_specs: str = ""
    image: str = ""
    gallery: str = ""
    discount_rule: str = ""
    promotions: str = ""
    source: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    source_order: int = 0
    duplicate_sources: tuple[dict[str, Any], ...] = ()
    conflict_fields: frozenset[str] = frozenset()

    @property
    def ambiguous(self) -> bool:
        return bool(self.conflict_fields)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sku", str(self.sku).strip())
        if not self.sku:
            raise ValueError("SKU vacío")


@dataclass(frozen=True, slots=True)
class TargetSpec:
    skus: tuple[str, ...] = ()
    brand: str | None = None
    category: str | None = None
    subcategory: str | None = None
    stock_lt: int | None = None
    stock_gt: int | None = None
    on_offer: bool | None = None
    visible: bool | None = None
    working_set_skus: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FieldPatch:
    values: dict[str, Any]
    fields: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", frozenset(self.values.keys()))


@dataclass(frozen=True, slots=True)
class AgentPlan:
    action: ActionType
    target: TargetSpec
    patch: FieldPatch | None = None
    risk: RiskLevel = RiskLevel.R0
    prompt_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
