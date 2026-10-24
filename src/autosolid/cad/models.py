"""Strict, immutable models for the initial ``CadSpec`` contract.

Geometric coordinates and vectors are expected in the canonical units declared by
``CadSpec.units``: millimetres for lengths and degrees for angles.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.1.0"

Point2D = tuple[float, float]
Vector3 = tuple[float, float, float]
BoundingBox = tuple[float, float, float, float]

Origin = Literal["extracted", "inferred", "user_supplied", "default"]
QuestionSeverity = Literal["critical", "major", "minor"]
DiagnosticSeverity = Literal["error", "warning", "info"]
QuestionStatus = Literal["open", "resolved"]

# Canonical internal units only. Convert at the ingestion boundary.
LengthUnit = Literal["mm"]
AngleUnit = Literal["deg"]
Unit = Literal["mm", "deg", "1"]

Quantity = Literal["length", "angle", "number"]


class CadModel(BaseModel):
    """Base model with strict fields and immutability."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class Units(CadModel):
    length: LengthUnit = "mm"
    angle: AngleUnit = "deg"


class Tolerance(CadModel):
    """Basic manufacturing tolerance carrier.

    ``symmetric`` uses ``value`` (+/-). ``range`` uses ``lower``/``upper``.
    ``iso_fit`` uses ``designation``. ``none`` carries no numeric bounds.
    """

    kind: Literal["symmetric", "range", "iso_fit", "none"] = "none"
    value: Decimal | None = None
    lower: Decimal | None = None
    upper: Decimal | None = None
    designation: str | None = None


class Source(CadModel):
    id: str
    kind: Literal["pdf", "image", "text", "user"]
    sha256: str | None = None
    page: int | None = None


class Evidence(CadModel):
    id: str
    source_id: str
    page: int | None = None
    view_id: str | None = None
    bbox: BoundingBox | None = None
    kind: str
    raw_text: str | None = None
    normalized_value: Decimal | None = None
    unit: Unit | None = None
    tolerance: Tolerance | None = None
    extractor: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class Parameter(CadModel):
    value: Decimal
    unit: Unit
    quantity: Quantity = "length"
    origin: Origin
    evidence_ids: list[str] = Field(default_factory=list)
    tolerance: Tolerance | None = None
    note: str | None = None


class Question(CadModel):
    id: str
    text: str
    severity: QuestionSeverity
    status: QuestionStatus = "open"


class Assumption(CadModel):
    id: str
    text: str
    severity: QuestionSeverity
    accepted: bool = False


class PlaneReference(CadModel):
    id: str
    kind: Literal["plane"]
    name: str
    origin: Vector3 = (0.0, 0.0, 0.0)
    x_axis: Vector3 = (1.0, 0.0, 0.0)
    y_axis: Vector3 = (0.0, 1.0, 0.0)


class AxisReference(CadModel):
    id: str
    kind: Literal["axis"]
    name: str | None = None
    origin: Vector3 = (0.0, 0.0, 0.0)
    direction: Vector3


Reference = Annotated[
    Union[PlaneReference, AxisReference],
    Field(discriminator="kind"),
]


class LineEntity(CadModel):
    id: str
    kind: Literal["line"]
    start: Point2D
    end: Point2D


class ClosedLoopConstraint(CadModel):
    kind: Literal["closed_loop"]
    entity_ids: list[str]


class CoincidentAxisConstraint(CadModel):
    kind: Literal["coincident_axis"]
    entity_id: str
    reference_id: str


Constraint = Annotated[
    Union[ClosedLoopConstraint, CoincidentAxisConstraint],
    Field(discriminator="kind"),
]


class Dimension(CadModel):
    """Linear sketch dimension tied to a parameter or an unsupported expression."""

    kind: Literal["distance"] = "distance"
    from_point: Point2D = Field(alias="from")
    to_point: Point2D = Field(alias="to")
    parameter: str | None = None
    expression: str | None = None


class Sketch(CadModel):
    id: str
    plane_id: str
    entities: list[LineEntity] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    dimensions: list[Dimension] = Field(default_factory=list)


class ExtrudeFeature(CadModel):
    id: str
    kind: Literal["extrude"]
    sketch_id: str
    distance: Decimal
    operation: Literal["new_body"] = "new_body"


class RevolveFeature(CadModel):
    id: str
    kind: Literal["revolve"]
    sketch_id: str
    axis_id: str
    angle: Decimal = Decimal("360")
    operation: Literal["new_body"] = "new_body"


Feature = Annotated[
    Union[ExtrudeFeature, RevolveFeature],
    Field(discriminator="kind"),
]


class Diagnostic(CadModel):
    code: str
    severity: DiagnosticSeverity
    path: str
    message: str


class CadSpec(CadModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    project_id: str
    revision: int = 0
    units: Units = Field(default_factory=Units)
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    parameters: dict[str, Parameter] = Field(default_factory=dict)
    references: list[Reference] = Field(default_factory=list)
    sketches: list[Sketch] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    open_questions: list[Question] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
