from autosolid.cad import validate_spec
from autosolid.cad.geometry import collinear_overlap
from tests.builders import codes, extrude_spec, make_sketch, revolve_spec


def test_collinear_overlap_requires_both_endpoints_on_the_line():
    assert not collinear_overlap(
        (0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (5.0, 10.0)
    )
    assert not collinear_overlap(
        (0.0, 0.0), (10.0, 0.0), (5.0, 0.0), (10.0, 5.0)
    )
    assert collinear_overlap(
        (0.0, 0.0), (10.0, 0.0), (5.0, 0.0), (15.0, 0.0)
    )


def test_zero_length_segment_is_reported():
    spec = extrude_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("bottom", (0.0, 0.0), (40.0, 0.0)),
                    ("right", (40.0, 0.0), (40.0, 20.0)),
                    ("top", (40.0, 20.0), (0.0, 20.0)),
                    ("left", (0.0, 20.0), (0.0, 0.0)),
                    ("zero", (0.0, 0.0), (0.0, 0.0)),
                ]
            )
        ]
    )
    assert "SEGMENT_ZERO_LENGTH" in codes(validate_spec(spec))


def test_open_loop_is_reported_as_not_closed():
    spec = extrude_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("bottom", (0.0, 0.0), (40.0, 0.0)),
                    ("right", (40.0, 0.0), (40.0, 20.0)),
                    ("top", (40.0, 20.0), (0.0, 20.0)),
                ]
            )
        ]
    )
    diagnostics = codes(validate_spec(spec))
    assert "SKETCH_NOT_CLOSED" in diagnostics
    assert "SKETCH_DISCONNECTED" not in diagnostics


def test_disconnected_loops_are_reported():
    spec = extrude_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("a1", (0.0, 0.0), (10.0, 0.0)),
                    ("a2", (10.0, 0.0), (5.0, 10.0)),
                    ("a3", (5.0, 10.0), (0.0, 0.0)),
                    ("b1", (20.0, 0.0), (30.0, 0.0)),
                    ("b2", (30.0, 0.0), (25.0, 10.0)),
                    ("b3", (25.0, 10.0), (20.0, 0.0)),
                ]
            )
        ]
    )
    assert "SKETCH_DISCONNECTED" in codes(validate_spec(spec))


def test_self_intersection_is_reported():
    spec = extrude_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("s1", (0.0, 0.0), (10.0, 10.0)),
                    ("s2", (10.0, 10.0), (0.0, 10.0)),
                    ("s3", (0.0, 10.0), (10.0, 0.0)),
                    ("s4", (10.0, 0.0), (0.0, 0.0)),
                ]
            )
        ]
    )
    assert "SKETCH_SELF_INTERSECTION" in codes(validate_spec(spec))


def test_adjacent_junction_is_not_a_self_intersection():
    spec = extrude_spec()
    diagnostics = codes(validate_spec(spec))
    assert "SKETCH_SELF_INTERSECTION" not in diagnostics
    assert "SKETCH_NOT_CLOSED" not in diagnostics


def test_adjacent_collinear_continuation_is_not_a_self_intersection():
    spec = extrude_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("bottom_a", (0.0, 0.0), (20.0, 0.0)),
                    ("bottom_b", (20.0, 0.0), (40.0, 0.0)),
                    ("right", (40.0, 0.0), (40.0, 20.0)),
                    ("top", (40.0, 20.0), (0.0, 20.0)),
                    ("left", (0.0, 20.0), (0.0, 0.0)),
                ]
            )
        ]
    )
    assert "SKETCH_SELF_INTERSECTION" not in codes(validate_spec(spec))


def test_adjacent_collinear_overlap_is_a_self_intersection():
    spec = extrude_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("s1", (0.0, 0.0), (10.0, 0.0)),
                    ("s2", (10.0, 0.0), (5.0, 0.0)),
                    ("s3", (5.0, 0.0), (0.0, 0.0)),
                ]
            )
        ]
    )
    assert "SKETCH_SELF_INTERSECTION" in codes(validate_spec(spec))


def test_empty_sketch_is_reported():
    spec = extrude_spec(sketches=[make_sketch(segments=[])])
    assert "SKETCH_EMPTY" in codes(validate_spec(spec))


def test_non_finite_coordinate_is_reported():
    spec = extrude_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("bottom", (float("inf"), 0.0), (40.0, 0.0)),
                    ("right", (40.0, 0.0), (40.0, 20.0)),
                    ("top", (40.0, 20.0), (0.0, 20.0)),
                    ("left", (0.0, 20.0), (float("inf"), 0.0)),
                ]
            )
        ]
    )
    assert "COORDINATE_NOT_FINITE" in codes(validate_spec(spec))


def test_valid_revolve_profile_touching_axis_is_allowed():
    spec = revolve_spec(
        sketches=[
            make_sketch(
                segments=[
                    ("bottom", (0.0, 0.0), (10.0, 0.0)),
                    ("right", (10.0, 0.0), (10.0, 10.0)),
                    ("top", (10.0, 10.0), (0.0, 10.0)),
                    ("left", (0.0, 10.0), (0.0, 0.0)),
                ]
            )
        ]
    )
    assert "REVOLVE_PROFILE_CROSSES_AXIS" not in codes(validate_spec(spec))
