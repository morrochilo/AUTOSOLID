from autosolid.cad import (
    AxisReference,
    ExtrudeFeature,
    PlaneReference,
    RevolveFeature,
    validate_spec,
)
from tests.builders import D, codes, extrude_spec, make_sketch, revolve_spec


def test_extrude_distance_must_be_positive_and_finite():
    spec = extrude_spec()
    feature = spec.features[0]

    zero = spec.model_copy(
        update={
            "features": [
                ExtrudeFeature(
                    id=feature.id,
                    kind="extrude",
                    sketch_id=feature.sketch_id,
                    distance=D("0"),
                )
            ]
        }
    )
    assert "EXTRUDE_DISTANCE_NOT_POSITIVE" in codes(validate_spec(zero))

    negative = spec.model_copy(
        update={
            "features": [
                ExtrudeFeature(
                    id=feature.id,
                    kind="extrude",
                    sketch_id=feature.sketch_id,
                    distance=D("-1.000"),
                )
            ]
        }
    )
    assert "EXTRUDE_DISTANCE_NOT_POSITIVE" in codes(validate_spec(negative))

    not_finite = spec.model_dump(mode="json")
    not_finite["features"][0]["distance"] = "NaN"
    assert "SCHEMA_INVALID" in codes(validate_spec(not_finite))


def test_revolve_axis_must_be_non_zero():
    spec = revolve_spec(
        references=[
            PlaneReference(id="front_plane", kind="plane", name="Front"),
            AxisReference(
                id="main_axis",
                kind="axis",
                direction=(0.0, 0.0, 0.0),
            ),
        ]
    )
    assert "AXIS_ZERO" in codes(validate_spec(spec))


def test_revolve_angle_range():
    base = revolve_spec()
    feature = base.features[0]
    assert isinstance(feature, RevolveFeature)

    for angle in ("0", "-10.000", "360.001"):
        spec = base.model_copy(
            update={
                "features": [
                    RevolveFeature(
                        id=feature.id,
                        kind="revolve",
                        sketch_id=feature.sketch_id,
                        axis_id=feature.axis_id,
                        angle=D(angle),
                    )
                ]
            }
        )
        assert "REVOLVE_ANGLE_OUT_OF_RANGE" in codes(validate_spec(spec))

    valid = base.model_copy(
        update={
            "features": [
                RevolveFeature(
                    id=feature.id,
                    kind="revolve",
                    sketch_id=feature.sketch_id,
                    axis_id=feature.axis_id,
                    angle=D("360"),
                )
            ]
        }
    )
    assert "REVOLVE_ANGLE_OUT_OF_RANGE" not in codes(validate_spec(valid))


def test_revolve_angle_must_be_finite():
    payload = revolve_spec().model_dump(mode="json")
    payload["features"][0]["angle"] = "NaN"
    assert "SCHEMA_INVALID" in codes(validate_spec(payload))


def test_profile_crossing_axis_is_reported():
    spec = revolve_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("bottom", (0.0, -5.0), (10.0, -5.0)),
                    ("right", (10.0, -5.0), (10.0, 5.0)),
                    ("top", (10.0, 5.0), (0.0, 5.0)),
                    ("left", (0.0, 5.0), (0.0, -5.0)),
                ]
            )
        ]
    )
    assert "REVOLVE_PROFILE_CROSSES_AXIS" in codes(validate_spec(spec))


def test_profile_crossing_axis_at_vertex_is_reported():
    spec = revolve_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("a", (0.0, 0.0), (10.0, 10.0)),
                    ("b", (10.0, 10.0), (20.0, 0.0)),
                    ("c", (20.0, 0.0), (10.0, -10.0)),
                    ("d", (10.0, -10.0), (0.0, 0.0)),
                ]
            )
        ]
    )
    assert "REVOLVE_PROFILE_CROSSES_AXIS" in codes(validate_spec(spec))


def test_axis_must_lie_in_sketch_plane():
    spec = revolve_spec(
        references=[
            PlaneReference(id="front_plane", kind="plane", name="Front"),
            AxisReference(
                id="main_axis",
                kind="axis",
                direction=(0.0, 0.0, 1.0),
            ),
        ]
    )
    assert "REVOLVE_AXIS_NOT_IN_PLANE" in codes(validate_spec(spec))
