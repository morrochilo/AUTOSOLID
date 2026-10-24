"""Small deterministic 2D/3D geometry helpers used by the validators."""

from __future__ import annotations

import math
from decimal import Decimal

from .models import Point2D, Vector3

EPS = 1e-9


def decimal_is_finite(value: Decimal) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


def values_are_finite(values: tuple[float, ...]) -> bool:
    return all(math.isfinite(value) for value in values)


def sub2(a: Point2D, b: Point2D) -> Point2D:
    return (a[0] - b[0], a[1] - b[1])


def add2(a: Point2D, b: Point2D) -> Point2D:
    return (a[0] + b[0], a[1] + b[1])


def scale2(value: float, point: Point2D) -> Point2D:
    return (value * point[0], value * point[1])


def cross2(a: Point2D, b: Point2D) -> float:
    return a[0] * b[1] - a[1] * b[0]


def dot2(a: Point2D, b: Point2D) -> float:
    return a[0] * b[0] + a[1] * b[1]


def norm2(value: Point2D) -> float:
    return math.hypot(value[0], value[1])


def sub3(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot3(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross3(a: Vector3, b: Vector3) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def norm3(value: Vector3) -> float:
    return math.sqrt(dot3(value, value))


def point_key(point: Point2D) -> tuple[float, float]:
    return (round(point[0], 9), round(point[1], 9))


def same_point(a: Point2D, b: Point2D, tolerance: float = EPS) -> bool:
    return math.isclose(a[0], b[0], abs_tol=tolerance) and math.isclose(
        a[1], b[1], abs_tol=tolerance
    )


def collinear_overlap(
    p1: Point2D,
    p2: Point2D,
    q1: Point2D,
    q2: Point2D,
    tolerance: float = EPS,
) -> bool:
    """Return True when two collinear segments share more than a point."""

    r = sub2(p2, p1)
    length = norm2(r)
    if length <= tolerance:
        return False
    line_tolerance = tolerance * max(1.0, length)
    if abs(cross2(r, sub2(q1, p1))) > line_tolerance:
        return False
    if abs(cross2(r, sub2(q2, p1))) > line_tolerance:
        return False

    axis = 0 if abs(r[0]) >= abs(r[1]) else 1
    a_low, a_high = sorted((p1[axis], p2[axis]))
    b_low, b_high = sorted((q1[axis], q2[axis]))
    overlap = min(a_high, b_high) - max(a_low, b_low)
    return overlap > tolerance


def segments_intersect(
    p1: Point2D,
    p2: Point2D,
    q1: Point2D,
    q2: Point2D,
    tolerance: float = EPS,
) -> bool:
    """Return True when two segments intersect at any point.

    The caller decides whether a shared endpoint is an allowed junction.
    """

    r = sub2(p2, p1)
    s = sub2(q2, q1)
    r_length = norm2(r)
    s_length = norm2(s)
    if r_length <= tolerance or s_length <= tolerance:
        return False

    denominator = cross2(r, s)
    q_minus_p = sub2(q1, p1)
    scale = max(1.0, r_length * s_length)

    if abs(denominator) <= tolerance * scale:
        if abs(cross2(q_minus_p, r)) > tolerance * max(1.0, r_length):
            return False
        return collinear_overlap(p1, p2, q1, q2, tolerance)

    t = cross2(q_minus_p, s) / denominator
    u = cross2(q_minus_p, r) / denominator
    return (
        -tolerance <= t <= 1.0 + tolerance
        and -tolerance <= u <= 1.0 + tolerance
    )


def project_point_to_plane(
    point: Vector3,
    plane_origin: Vector3,
    plane_x_axis: Vector3,
    plane_y_axis: Vector3,
) -> Point2D:
    relative = sub3(point, plane_origin)
    return (dot3(relative, plane_x_axis), dot3(relative, plane_y_axis))


def plane_normal(plane_x_axis: Vector3, plane_y_axis: Vector3) -> Vector3:
    return cross3(plane_x_axis, plane_y_axis)


def point_lies_in_plane(
    point: Vector3,
    plane_origin: Vector3,
    normal: Vector3,
    tolerance: float = EPS,
) -> bool:
    normal_length = norm3(normal)
    if normal_length <= tolerance:
        return False
    distance = dot3(sub3(point, plane_origin), normal)
    return abs(distance) <= tolerance * max(1.0, normal_length)


def direction_lies_in_plane(
    direction: Vector3,
    normal: Vector3,
    tolerance: float = EPS,
) -> bool:
    direction_length = norm3(direction)
    normal_length = norm3(normal)
    if direction_length <= tolerance or normal_length <= tolerance:
        return False
    return abs(dot3(direction, normal)) <= tolerance * max(
        1.0, direction_length * normal_length
    )


def axis_profile_crosses(
    segments: list[tuple[Point2D, Point2D]],
    axis_origin: Point2D,
    axis_direction: Point2D,
    tolerance: float = EPS,
) -> bool:
    """Detect whether a closed profile crosses an axis line.

    Touching the axis or running along it is allowed; moving from one side to the
    other is not.
    """

    direction_length = norm2(axis_direction)
    if direction_length <= tolerance:
        return False
    unit_direction = scale2(1.0 / direction_length, axis_direction)

    distances: list[tuple[float, float]] = []
    for start, end in segments:
        distances.append(
            (
                cross2(unit_direction, sub2(start, axis_origin)),
                cross2(unit_direction, sub2(end, axis_origin)),
            )
        )
        if distances[-1][0] * distances[-1][1] < 0.0:
            if (
                distances[-1][0] > tolerance and distances[-1][1] < -tolerance
            ) or (
                distances[-1][0] < -tolerance and distances[-1][1] > tolerance
            ):
                return True

    incidents: dict[tuple[float, float], list[Point2D]] = {}
    for start, end in segments:
        start_key = point_key(start)
        end_key = point_key(end)
        incidents.setdefault(start_key, []).append(end)
        incidents.setdefault(end_key, []).append(start)

    for node_key, neighbors in incidents.items():
        node_distance = cross2(unit_direction, sub2(node_key, axis_origin))
        if abs(node_distance) > tolerance:
            continue
        positive = False
        negative = False
        for neighbor in neighbors:
            neighbor_distance = cross2(
                unit_direction, sub2(neighbor, axis_origin)
            )
            if neighbor_distance > tolerance:
                positive = True
            elif neighbor_distance < -tolerance:
                negative = True
        if positive and negative:
            return True

    return False
