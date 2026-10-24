"""Small, explicit builders for CadSpec tests."""

from __future__ import annotations

from decimal import Decimal

from autosolid.cad.models import (
    Assumption,
    AxisReference,
    CadSpec,
    ClosedLoopConstraint,
    CoincidentAxisConstraint,
    Diagnostic,
    Dimension,
    Evidence,
    ExtrudeFeature,
    LineEntity,
    Parameter,
    PlaneReference,
    Question,
    RevolveFeature,
    Sketch,
    Source,
    Tolerance,
)

D = Decimal


def make_source(source_id: str = "src_pdf") -> Source:
    return Source(
        id=source_id,
        kind="pdf",
        sha256="0" * 64,
        page=1,
    )


def make_evidence(
    evidence_id: str,
    value: str = "50.000",
    source_id: str = "src_pdf",
) -> Evidence:
    return Evidence(
        id=evidence_id,
        source_id=source_id,
        page=1,
        view_id="view_front",
        bbox=(100.0, 220.0, 180.0, 260.0),
        kind="linear_dimension",
        raw_text=value,
        normalized_value=D(value),
        unit="mm",
        tolerance=Tolerance(kind="symmetric", value=D("0.050")),
        extractor="test-builder",
        confidence=0.98,
    )


def make_parameter(
    value: str = "50.000",
    *,
    unit: str = "mm",
    quantity: str = "length",
    origin: str = "extracted",
    evidence_ids: list[str] | None = None,
) -> Parameter:
    return Parameter(
        value=D(value),
        unit=unit,
        quantity=quantity,
        origin=origin,
        evidence_ids=[] if evidence_ids is None else evidence_ids,
    )


def make_line(entity_id: str, start: tuple[float, float], end: tuple[float, float]) -> LineEntity:
    return LineEntity(
        id=entity_id,
        kind="line",
        start=start,
        end=end,
    )


def make_sketch(
    *,
    sketch_id: str = "profile",
    plane_id: str = "front_plane",
    segments: list[tuple[str, tuple[float, float], tuple[float, float]]] | None = None,
    constraints: list | None = None,
    dimensions: list[Dimension] | None = None,
) -> Sketch:
    if segments is None:
        segments = [
            ("l1", (0.0, 0.0), (0.0, 25.0)),
            ("l2", (0.0, 25.0), (80.0, 25.0)),
            ("l3", (80.0, 25.0), (80.0, 0.0)),
            ("axis_segment", (80.0, 0.0), (0.0, 0.0)),
        ]
    entities = [make_line(entity_id, start, end) for entity_id, start, end in segments]
    return Sketch(
        id=sketch_id,
        plane_id=plane_id,
        entities=entities,
        constraints=[] if constraints is None else constraints,
        dimensions=[] if dimensions is None else dimensions,
    )


def revolve_spec(
    *,
    sources: list[Source] | None = None,
    evidence: list[Evidence] | None = None,
    parameters: dict[str, Parameter] | None = None,
    references: list | None = None,
    sketches: list[Sketch] | None = None,
    features: list | None = None,
    open_questions: list[Question] | None = None,
    assumptions: list[Assumption] | None = None,
) -> CadSpec:
    if sources is None:
        sources = [make_source()]
    if evidence is None:
        evidence = [
            make_evidence("ev_dim_01", "50.000"),
            make_evidence("ev_dim_02", "80.000"),
        ]
    if parameters is None:
        parameters = {
            "outer_diameter": make_parameter(
                "50.000", evidence_ids=["ev_dim_01"]
            ),
            "length": make_parameter("80.000", evidence_ids=["ev_dim_02"]),
            "radius": make_parameter(
                "25.000",
                origin="inferred",
                evidence_ids=["ev_dim_01"],
            ),
        }
    if references is None:
        references = [
            PlaneReference(id="front_plane", kind="plane", name="Front"),
            AxisReference(
                id="main_axis",
                kind="axis",
                name="Main axis",
                origin=(0.0, 0.0, 0.0),
                direction=(1.0, 0.0, 0.0),
            ),
        ]
    if sketches is None:
        sketches = [
            make_sketch(
                constraints=[
                    ClosedLoopConstraint(
                        kind="closed_loop",
                        entity_ids=["l1", "l2", "l3", "axis_segment"],
                    ),
                    CoincidentAxisConstraint(
                        kind="coincident_axis",
                        entity_id="axis_segment",
                        reference_id="main_axis",
                    ),
                ],
                dimensions=[
                    Dimension(
                        **{"from": (0.0, 0.0), "to": (80.0, 0.0)},
                        parameter="length",
                    ),
                    Dimension(
                        **{"from": (0.0, 0.0), "to": (0.0, 25.0)},
                        parameter="radius",
                    ),
                ],
            )
        ]
    if features is None:
        features = [
            RevolveFeature(
                id="body",
                kind="revolve",
                sketch_id="profile",
                axis_id="main_axis",
                angle=D("360"),
            )
        ]
    return CadSpec(
        project_id="prj_test",
        revision=1,
        sources=sources,
        evidence=evidence,
        parameters=parameters,
        references=references,
        sketches=sketches,
        features=features,
        open_questions=[] if open_questions is None else open_questions,
        assumptions=[] if assumptions is None else assumptions,
    )


def extrude_spec(
    *,
    parameters: dict[str, Parameter] | None = None,
    references: list | None = None,
    sketches: list[Sketch] | None = None,
    features: list | None = None,
    open_questions: list[Question] | None = None,
) -> CadSpec:
    if parameters is None:
        parameters = {
            "width": make_parameter("40.000", origin="user_supplied"),
            "height": make_parameter("20.000", origin="user_supplied"),
        }
    if references is None:
        references = [PlaneReference(id="front_plane", kind="plane", name="Front")]
    if sketches is None:
        sketches = [
            make_sketch(
                segments=[
                    ("bottom", (0.0, 0.0), (40.0, 0.0)),
                    ("right", (40.0, 0.0), (40.0, 20.0)),
                    ("top", (40.0, 20.0), (0.0, 20.0)),
                    ("left", (0.0, 20.0), (0.0, 0.0)),
                ],
                constraints=[
                    ClosedLoopConstraint(
                        kind="closed_loop",
                        entity_ids=["bottom", "right", "top", "left"],
                    )
                ],
                dimensions=[
                    Dimension(
                        **{"from": (0.0, 0.0), "to": (40.0, 0.0)},
                        parameter="width",
                    ),
                    Dimension(
                        **{"from": (0.0, 0.0), "to": (0.0, 20.0)},
                        parameter="height",
                    ),
                ],
            )
        ]
    if features is None:
        features = [
            ExtrudeFeature(
                id="body",
                kind="extrude",
                sketch_id="profile",
                distance=D("10.000"),
            )
        ]
    return CadSpec(
        project_id="prj_extrude",
        revision=1,
        sources=[],
        evidence=[],
        parameters=parameters,
        references=references,
        sketches=sketches,
        features=features,
        open_questions=[] if open_questions is None else open_questions,
    )


def codes(diagnostics: list[Diagnostic]) -> set[str]:
    return {diagnostic.code for diagnostic in diagnostics}
