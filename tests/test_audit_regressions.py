from autosolid.cad import Assumption, PlaneReference, validate_spec
from tests.builders import codes, extrude_spec, make_sketch, revolve_spec


def test_audit_non_collinear_adjacent_segments_are_valid():
    spec = extrude_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("bottom", (0.0, 0.0), (10.0, 0.0)),
                    ("right", (10.0, 0.0), (5.0, 10.0)),
                    ("left", (5.0, 10.0), (0.0, 0.0)),
                ]
            )
        ]
    )
    assert validate_spec(spec) == []


def test_audit_dimension_must_match_referenced_parameter():
    spec = extrude_spec()
    parameters = dict(spec.parameters)
    parameters["width"] = parameters["width"].model_copy(
        update={"value": parameters["width"].value + 1}
    )
    spec = spec.model_copy(update={"parameters": parameters})

    assert "DIMENSION_LENGTH_MISMATCH" in codes(validate_spec(spec))


def test_audit_critical_assumption_requires_acceptance():
    spec = revolve_spec(
        assumptions=[
            Assumption(
                id="axis_assumption",
                text="Se presupone el eje principal",
                severity="critical",
                accepted=False,
            )
        ]
    )

    assert "ASSUMPTION_NOT_ACCEPTED" in codes(validate_spec(spec))


def test_audit_plane_basis_must_be_orthonormal():
    spec = revolve_spec(
        references=[
            PlaneReference(
                id="front_plane",
                kind="plane",
                name="Front",
                x_axis=(2.0, 0.0, 0.0),
            ),
            *revolve_spec().references[1:],
        ]
    )

    assert "PLANE_BASIS_INVALID" in codes(validate_spec(spec))
