from autosolid.cad import (
    Assumption,
    AxisReference,
    ClosedLoopConstraint,
    CoincidentAxisConstraint,
    Dimension,
    Evidence,
    Parameter,
    PlaneReference,
    Question,
    Tolerance,
    validate_spec,
)
from tests.builders import (
    D,
    codes,
    extrude_spec,
    make_evidence,
    make_parameter,
    make_sketch,
    make_source,
    revolve_spec,
)


def test_duplicate_ids_are_reported():
    duplicate_sources = revolve_spec(
        sources=[make_source("src_pdf"), make_source("src_pdf")]
    )
    assert "DUPLICATE_ID" in codes(validate_spec(duplicate_sources))

    duplicate_evidence = revolve_spec(
        evidence=[make_evidence("ev_dim_01"), make_evidence("ev_dim_01")]
    )
    assert "DUPLICATE_ID" in codes(validate_spec(duplicate_evidence))

    duplicate_references = revolve_spec(
        references=[
            PlaneReference(id="front_plane", kind="plane", name="Front"),
            PlaneReference(id="front_plane", kind="plane", name="Other"),
            AxisReference(id="main_axis", kind="axis", direction=(1.0, 0.0, 0.0)),
        ]
    )
    assert "DUPLICATE_ID" in codes(validate_spec(duplicate_references))

    duplicate_sketches = revolve_spec(
        sketches=[make_sketch(), make_sketch()]
    )
    assert "DUPLICATE_ID" in codes(validate_spec(duplicate_sketches))

    duplicate_entities = revolve_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("l1", (0.0, 0.0), (10.0, 0.0)),
                    ("l1", (10.0, 0.0), (10.0, 10.0)),
                    ("l3", (10.0, 10.0), (0.0, 0.0)),
                ]
            )
        ]
    )
    assert "DUPLICATE_ID" in codes(validate_spec(duplicate_entities))

    feature = revolve_spec().features[0]
    duplicate_features = revolve_spec(features=[feature, feature])
    assert "DUPLICATE_ID" in codes(validate_spec(duplicate_features))

    duplicate_questions = revolve_spec(
        open_questions=[
            Question(id="q1", text="a", severity="minor"),
            Question(id="q1", text="b", severity="minor"),
        ]
    )
    assert "DUPLICATE_ID" in codes(validate_spec(duplicate_questions))

    duplicate_assumptions = revolve_spec(
        assumptions=[
            Assumption(id="a1", text="a", severity="minor"),
            Assumption(id="a1", text="b", severity="minor"),
        ]
    )
    assert "DUPLICATE_ID" in codes(validate_spec(duplicate_assumptions))


def test_missing_evidence_source_is_reported():
    spec = revolve_spec(
        evidence=[make_evidence("ev_dim_01", source_id="src_missing")]
    )
    assert "EVIDENCE_SOURCE_MISSING" in codes(validate_spec(spec))


def test_missing_parameter_evidence_is_reported():
    spec = revolve_spec(
        parameters={
            "length": make_parameter("80.000", evidence_ids=["ev_missing"])
        }
    )
    assert "PARAMETER_EVIDENCE_MISSING" in codes(validate_spec(spec))


def test_missing_dimension_parameter_is_reported():
    spec = revolve_spec(
        sketches=[
            make_sketch(
                dimensions=[
                    Dimension(
                        **{"from": (0.0, 0.0), "to": (80.0, 0.0)},
                        parameter="missing_parameter",
                    )
                ]
            )
        ]
    )
    assert "DIMENSION_PARAMETER_MISSING" in codes(validate_spec(spec))


def test_missing_and_invalid_sketch_plane_are_reported():
    missing = revolve_spec(
        sketches=[make_sketch(plane_id="missing_plane")]
    )
    assert "SKETCH_PLANE_MISSING" in codes(validate_spec(missing))

    invalid = revolve_spec(
        references=[
            AxisReference(id="front_plane", kind="axis", direction=(1.0, 0.0, 0.0)),
            AxisReference(id="main_axis", kind="axis", direction=(1.0, 0.0, 0.0)),
        ]
    )
    assert "SKETCH_PLANE_INVALID" in codes(validate_spec(invalid))


def test_missing_feature_references_are_reported():
    missing_sketch = revolve_spec()
    missing_sketch = missing_sketch.model_copy(
        update={
            "features": [
                missing_sketch.features[0].model_copy(
                    update={"sketch_id": "missing_sketch"}
                )
            ]
        }
    )
    assert "FEATURE_SKETCH_MISSING" in codes(validate_spec(missing_sketch))

    missing_axis = revolve_spec()
    missing_axis = missing_axis.model_copy(
        update={
            "features": [
                missing_axis.features[0].model_copy(
                    update={"axis_id": "missing_axis"}
                )
            ]
        }
    )
    assert "FEATURE_AXIS_MISSING" in codes(validate_spec(missing_axis))

    invalid_axis = revolve_spec()
    invalid_axis = invalid_axis.model_copy(
        update={
            "features": [
                invalid_axis.features[0].model_copy(
                    update={"axis_id": "front_plane"}
                )
            ]
        }
    )
    assert "FEATURE_AXIS_INVALID" in codes(validate_spec(invalid_axis))


def test_constraint_references_are_validated():
    missing_entity = revolve_spec(
        sketches=[
            make_sketch(
                constraints=[
                    ClosedLoopConstraint(
                        kind="closed_loop", entity_ids=["missing_entity"]
                    )
                ]
            )
        ]
    )
    assert "CONSTRAINT_ENTITY_MISSING" in codes(validate_spec(missing_entity))

    missing_reference = revolve_spec(
        sketches=[
            make_sketch(
                constraints=[
                    CoincidentAxisConstraint(
                        kind="coincident_axis",
                        entity_id="axis_segment",
                        reference_id="missing_reference",
                    )
                ]
            )
        ]
    )
    assert "CONSTRAINT_REFERENCE_MISSING" in codes(validate_spec(missing_reference))

    invalid_reference = revolve_spec(
        sketches=[
            make_sketch(
                constraints=[
                    CoincidentAxisConstraint(
                        kind="coincident_axis",
                        entity_id="axis_segment",
                        reference_id="front_plane",
                    )
                ]
            )
        ]
    )
    assert "CONSTRAINT_REFERENCE_INVALID" in codes(validate_spec(invalid_reference))


def test_non_finite_parameter_is_rejected_by_schema():
    payload = revolve_spec().model_dump(mode="json")
    payload["parameters"]["length"]["value"] = "NaN"
    assert "SCHEMA_INVALID" in codes(validate_spec(payload))


def test_non_finite_axis_direction_is_reported():
    spec = revolve_spec(
        references=[
            PlaneReference(id="front_plane", kind="plane", name="Front"),
            AxisReference(
                id="main_axis",
                kind="axis",
                direction=(float("inf"), 0.0, 0.0),
            ),
        ]
    )
    assert "NUMBER_NOT_FINITE" in codes(validate_spec(spec))


def test_non_positive_length_parameter_is_reported():
    spec = revolve_spec(
        parameters={"length": make_parameter("0", origin="user_supplied")}
    )
    assert "PARAMETER_NOT_POSITIVE" in codes(validate_spec(spec))


def test_unit_quantity_mismatch_is_reported():
    spec = revolve_spec(
        parameters={"length": make_parameter("80.000", unit="deg")}
    )
    assert "UNIT_MISMATCH" in codes(validate_spec(spec))


def test_critical_open_question_blocks_but_resolved_one_does_not():
    blocked = revolve_spec(
        open_questions=[Question(id="q1", text="¿Diámetro?", severity="critical")]
    )
    assert "QUESTION_CRITICAL_OPEN" in codes(validate_spec(blocked))

    resolved = revolve_spec(
        open_questions=[
            Question(
                id="q1",
                text="¿Diámetro?",
                severity="critical",
                status="resolved",
            )
        ]
    )
    assert "QUESTION_CRITICAL_OPEN" not in codes(validate_spec(resolved))

    major = revolve_spec(
        open_questions=[Question(id="q2", text="¿Acabado?", severity="major")]
    )
    assert "QUESTION_CRITICAL_OPEN" not in codes(validate_spec(major))


def test_invalid_tolerances_are_reported():
    bad_parameter_tolerance = revolve_spec(
        parameters={
            "length": Parameter(
                value=D("80.000"),
                unit="mm",
                origin="user_supplied",
                tolerance=Tolerance(kind="symmetric"),
            )
        }
    )
    assert "TOLERANCE_INVALID" in codes(validate_spec(bad_parameter_tolerance))

    bad_evidence_tolerance = revolve_spec(
        evidence=[
            Evidence(
                id="ev_dim_01",
                source_id="src_pdf",
                kind="linear_dimension",
                tolerance=Tolerance(
                    kind="range", lower=D("2.000"), upper=D("1.000")
                ),
            )
        ]
    )
    assert "TOLERANCE_INVALID" in codes(validate_spec(bad_evidence_tolerance))


def test_expression_is_explicitly_unsupported():
    spec = revolve_spec(
        sketches=[
            make_sketch(
                dimensions=[
                    Dimension(
                        **{"from": (0.0, 0.0), "to": (25.0, 0.0)},
                        expression="outer_diameter / 2",
                    )
                ]
            )
        ]
    )
    diagnostics = validate_spec(spec)
    assert "DIMENSION_EXPRESSION_UNSUPPORTED" in codes(diagnostics)
    assert all(diagnostic.code != "SCHEMA_INVALID" for diagnostic in diagnostics)


def test_dimension_without_parameter_or_expression_is_reported():
    spec = revolve_spec(
        sketches=[
            make_sketch(
                dimensions=[
                    Dimension(**{"from": (0.0, 0.0), "to": (25.0, 0.0)})
                ]
            )
        ]
    )
    assert "DIMENSION_VALUE_MISSING" in codes(validate_spec(spec))


def test_dimension_length_must_match_parameter():
    assert "DIMENSION_LENGTH_MISMATCH" not in codes(validate_spec(extrude_spec()))

    spec = extrude_spec()
    parameters = dict(spec.parameters)
    parameters["width"] = parameters["width"].model_copy(
        update={"value": parameters["width"].value + 1}
    )
    mismatched = spec.model_copy(update={"parameters": parameters})
    assert "DIMENSION_LENGTH_MISMATCH" in codes(validate_spec(mismatched))


def test_dimension_length_accepts_exact_diagonal():
    spec = extrude_spec(
        parameters={
            "diagonal": make_parameter("5.000", origin="user_supplied"),
        },
        sketches=[
            make_sketch(
                segments=[
                    ("a", (0.0, 0.0), (3.0, 0.0)),
                    ("b", (3.0, 0.0), (3.0, 4.0)),
                    ("c", (3.0, 4.0), (0.0, 0.0)),
                ],
                dimensions=[
                    Dimension(
                        **{"from": (0.0, 0.0), "to": (3.0, 4.0)},
                        parameter="diagonal",
                    )
                ],
            )
        ],
    )
    assert "DIMENSION_LENGTH_MISMATCH" not in codes(validate_spec(spec))


def test_dimension_requires_length_parameter():
    spec = extrude_spec(
        parameters={
            "angle_parameter": make_parameter(
                "45.000",
                unit="deg",
                quantity="angle",
                origin="user_supplied",
            )
        },
        sketches=[
            make_sketch(
                dimensions=[
                    Dimension(
                        **{"from": (0.0, 0.0), "to": (80.0, 0.0)},
                        parameter="angle_parameter",
                    )
                ]
            )
        ],
    )
    diagnostics = codes(validate_spec(spec))
    assert "UNIT_MISMATCH" in diagnostics
    assert "DIMENSION_LENGTH_MISMATCH" not in diagnostics


def test_assumptions_require_acceptance_for_critical_and_major():
    critical = revolve_spec(
        assumptions=[
            Assumption(
                id="axis_assumption",
                text="Se presupone el eje principal",
                severity="critical",
                accepted=False,
            )
        ]
    )
    assert "ASSUMPTION_NOT_ACCEPTED" in codes(validate_spec(critical))

    major = revolve_spec(
        assumptions=[
            Assumption(
                id="finish_assumption",
                text="Se presupone el acabado",
                severity="major",
                accepted=False,
            )
        ]
    )
    assert "ASSUMPTION_NOT_ACCEPTED" in codes(validate_spec(major))

    accepted = revolve_spec(
        assumptions=[
            Assumption(
                id="axis_assumption",
                text="Se presupone el eje principal",
                severity="critical",
                accepted=True,
            )
        ]
    )
    assert "ASSUMPTION_NOT_ACCEPTED" not in codes(validate_spec(accepted))

    minor = revolve_spec(
        assumptions=[
            Assumption(
                id="note_assumption",
                text="Nota de presentación",
                severity="minor",
                accepted=False,
            )
        ]
    )
    assert "ASSUMPTION_NOT_ACCEPTED" not in codes(validate_spec(minor))


def test_plane_basis_must_be_orthonormal():
    axis = AxisReference(
        id="main_axis",
        kind="axis",
        direction=(1.0, 0.0, 0.0),
    )
    scaled = revolve_spec(
        references=[
            PlaneReference(
                id="front_plane",
                kind="plane",
                name="Front",
                x_axis=(2.0, 0.0, 0.0),
            ),
            axis,
        ]
    )
    assert "PLANE_BASIS_INVALID" in codes(validate_spec(scaled))

    non_orthogonal = revolve_spec(
        references=[
            PlaneReference(
                id="front_plane",
                kind="plane",
                name="Front",
                y_axis=(1.0, 0.0, 0.0),
            ),
            axis,
        ]
    )
    assert "PLANE_BASIS_INVALID" in codes(validate_spec(non_orthogonal))

    zero_axis = revolve_spec(
        references=[
            PlaneReference(
                id="front_plane",
                kind="plane",
                name="Front",
                x_axis=(0.0, 0.0, 0.0),
            ),
            axis,
        ]
    )
    assert "PLANE_BASIS_INVALID" in codes(validate_spec(zero_axis))

    assert "PLANE_BASIS_INVALID" not in codes(validate_spec(revolve_spec()))
