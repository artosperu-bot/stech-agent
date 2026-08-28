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


class MutationMode(str, Enum):
    """How an instruction is allowed to affect product fields."""

    READ = "READ"
    FILL_MISSING = "FILL_MISSING"
    PATCH = "PATCH"
    REPLACE_SECTION = "REPLACE_SECTION"


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
    name: str | None = None
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
    """A patch that carries its own hard authorization mask.

    ``authorized_fields`` is enforced in the domain object itself so an LLM,
    router or caller cannot accidentally smuggle an extra field into the
    executor. Existing callers that do not pass the mask remain compatible:
    their explicit value keys become the authorization mask.
    """

    values: dict[str, Any]
    mode: MutationMode = MutationMode.PATCH
    section: str | None = None
    authorized_fields: frozenset[str] | None = None
    fields: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        fields = frozenset(self.values.keys())
        authorized = fields if self.authorized_fields is None else frozenset(self.authorized_fields)
        unauthorized = fields - authorized
        if unauthorized:
            raise ValueError("Campos no autorizados: " + ", ".join(sorted(unauthorized)))
        if self.mode is MutationMode.READ and fields:
            raise ValueError("READ no puede contener valores para modificar")
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "authorized_fields", authorized)


@dataclass(frozen=True, slots=True)
class AgentPlan:
    action: ActionType
    target: TargetSpec
    patch: FieldPatch | None = None
    risk: RiskLevel = RiskLevel.R0
    prompt_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
