"""Deterministic structural and geometric validation for ``CadSpec``.

``validate_spec`` returns diagnostics instead of raising for expected schema,
reference and geometry problems. It never attempts to repair the specification.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import ValidationError

from .geometry import (
    EPS,
    axis_profile_crosses,
    decimal_is_finite,
    collinear_overlap,
    direction_lies_in_plane,
    dot3,
    norm2,
    norm3,
    plane_normal,
    point_key,
    point_lies_in_plane,
    project_point_to_plane,
    segments_intersect,
    sub2,
    values_are_finite,
)
from .models import (
    AxisReference,
    CadSpec,
    ClosedLoopConstraint,
    CoincidentAxisConstraint,
    Diagnostic,
    Dimension,
    Evidence,
    ExtrudeFeature,
    Parameter,
    PlaneReference,
    RevolveFeature,
    Sketch,
    Tolerance,
)

T = TypeVar("T")

DIMENSION_LENGTH_TOLERANCE = Decimal("1e-9")


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity="error",
        path=path,
        message=message,
    )


def _format_location(location: Sequence[Any]) -> str:
    formatted = ""
    for part in location:
        if isinstance(part, int):
            formatted += f"[{part}]"
        else:
            formatted = f"{formatted}.{part}" if formatted else str(part)
    return formatted or "$"


def _schema_diagnostics(error: ValidationError) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for detail in error.errors():
        diagnostics.append(
            _diagnostic(
                "SCHEMA_INVALID",
                _format_location(detail.get("loc", ())),
                str(detail.get("msg", "Entrada inválida")),
            )
        )
    return diagnostics


def validate_spec(spec: CadSpec | Mapping[str, Any]) -> list[Diagnostic]:
    """Validate a ``CadSpec`` and return stable, serialisable diagnostics.

    A mapping is accepted for callers at the JSON boundary. Invalid schema input
    yields ``SCHEMA_INVALID`` diagnostics rather than a raised exception.
    """

    if not isinstance(spec, CadSpec):
        try:
            spec = CadSpec.model_validate(spec)
        except ValidationError as error:
            return _schema_diagnostics(error)

    diagnostics: list[Diagnostic] = []
    _validate_spec(spec, diagnostics)
    return diagnostics


def _index_by_id(
    items: Sequence[T],
    collection: str,
    diagnostics: list[Diagnostic],
) -> dict[str, T]:
    indexed: dict[str, T] = {}
    for index, item in enumerate(items):
        item_id = getattr(item, "id")
        if not item_id:
            diagnostics.append(
                _diagnostic(
                    "ID_EMPTY",
                    f"{collection}[{index}].id",
                    "El identificador no puede estar vacío.",
                )
            )
        if item_id in indexed:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_ID",
                    f"{collection}[{index}].id",
                    f"El identificador '{item_id}' está repetido en {collection}.",
                )
            )
            continue
        indexed[item_id] = item
    return indexed


def _validate_spec(spec: CadSpec, diagnostics: list[Diagnostic]) -> None:
    sources = _index_by_id(spec.sources, "sources", diagnostics)
    evidence = _index_by_id(spec.evidence, "evidence", diagnostics)
    references = _index_by_id(spec.references, "references", diagnostics)
    sketches = _index_by_id(spec.sketches, "sketches", diagnostics)
    _index_by_id(spec.features, "features", diagnostics)
    _index_by_id(spec.open_questions, "open_questions", diagnostics)
    _index_by_id(spec.assumptions, "assumptions", diagnostics)

    _validate_evidence(spec, sources, evidence, diagnostics)
    _validate_parameters(spec, evidence, diagnostics)
    _validate_references(spec, diagnostics)

    plane_by_id = {
        reference.id: reference
        for reference in references.values()
        if isinstance(reference, PlaneReference)
    }
    axis_by_id = {
        reference.id: reference
        for reference in references.values()
        if isinstance(reference, AxisReference)
    }
    sketch_by_id = {
        sketch.id: sketch for sketch in sketches.values()
    }

    for index, sketch in enumerate(spec.sketches):
        _validate_sketch(
            sketch,
            index,
            references,
            plane_by_id,
            spec.parameters,
            diagnostics,
        )

    for index, feature in enumerate(spec.features):
        _validate_feature(
            feature,
            index,
            references,
            sketch_by_id,
            plane_by_id,
            axis_by_id,
            diagnostics,
        )

    for index, question in enumerate(spec.open_questions):
        if question.severity == "critical" and question.status == "open":
            diagnostics.append(
                _diagnostic(
                    "QUESTION_CRITICAL_OPEN",
                    f"open_questions[{index}]",
                    f"La pregunta crítica '{question.id}' sigue abierta y bloquea la construcción.",
                )
            )

    for index, assumption in enumerate(spec.assumptions):
        if assumption.severity in {"critical", "major"} and not assumption.accepted:
            diagnostics.append(
                _diagnostic(
                    "ASSUMPTION_NOT_ACCEPTED",
                    f"assumptions[{index}]",
                    (
                        f"El supuesto '{assumption.id}' de severidad "
                        f"'{assumption.severity}' no está aceptado."
                    ),
                )
            )


def _validate_evidence(
    spec: CadSpec,
    sources: dict[str, Any],
    evidence: dict[str, Evidence],
    diagnostics: list[Diagnostic],
) -> None:
    for index, item in enumerate(spec.evidence):
        path = f"evidence[{index}]"
        if item.source_id not in sources:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_SOURCE_MISSING",
                    f"{path}.source_id",
                    f"La fuente '{item.source_id}' no existe.",
                )
            )
        if item.normalized_value is not None and not decimal_is_finite(
            item.normalized_value
        ):
            diagnostics.append(
                _diagnostic(
                    "NUMBER_NOT_FINITE",
                    f"{path}.normalized_value",
                    "El valor normalizado debe ser finito.",
                )
            )
        if item.bbox is not None and not values_are_finite(item.bbox):
            diagnostics.append(
                _diagnostic(
                    "NUMBER_NOT_FINITE",
                    f"{path}.bbox",
                    "La caja de evidencia debe contener números finitos.",
                )
            )
        _validate_tolerance(item.tolerance, f"{path}.tolerance", diagnostics)


def _validate_parameters(
    spec: CadSpec,
    evidence: dict[str, Evidence],
    diagnostics: list[Diagnostic],
) -> None:
    expected_units = {
        "length": {"mm"},
        "angle": {"deg"},
        "number": {"1"},
    }
    for parameter_id, parameter in spec.parameters.items():
        path = f"parameters.{parameter_id}"
        if not parameter_id:
            diagnostics.append(
                _diagnostic(
                    "ID_EMPTY",
                    "parameters",
                    "El identificador de parámetro no puede estar vacío.",
                )
            )
        if not decimal_is_finite(parameter.value):
            diagnostics.append(
                _diagnostic(
                    "PARAMETER_NOT_FINITE",
                    f"{path}.value",
                    "El valor del parámetro debe ser finito.",
                )
            )
        elif parameter.quantity == "length" and parameter.value <= 0:
            diagnostics.append(
                _diagnostic(
                    "PARAMETER_NOT_POSITIVE",
                    f"{path}.value",
                    "Un parámetro de longitud debe ser mayor que cero.",
                )
            )

        if parameter.unit not in expected_units[parameter.quantity]:
            diagnostics.append(
                _diagnostic(
                    "UNIT_MISMATCH",
                    f"{path}.unit",
                    (
                        f"La unidad '{parameter.unit}' no corresponde a la magnitud "
                        f"'{parameter.quantity}'."
                    ),
                )
            )

        for evidence_index, evidence_id in enumerate(parameter.evidence_ids):
            if evidence_id not in evidence:
                diagnostics.append(
                    _diagnostic(
                        "PARAMETER_EVIDENCE_MISSING",
                        f"{path}.evidence_ids[{evidence_index}]",
                        f"La evidencia '{evidence_id}' no existe.",
                    )
                )
        _validate_tolerance(parameter.tolerance, f"{path}.tolerance", diagnostics)


def _validate_references(spec: CadSpec, diagnostics: list[Diagnostic]) -> None:
    for index, reference in enumerate(spec.references):
        path = f"references[{index}]"
        if isinstance(reference, PlaneReference):
            vectors = (
                ("origin", reference.origin),
                ("x_axis", reference.x_axis),
                ("y_axis", reference.y_axis),
            )
            for field_name, vector in vectors:
                if not values_are_finite(vector):
                    diagnostics.append(
                        _diagnostic(
                            "NUMBER_NOT_FINITE",
                            f"{path}.{field_name}",
                            "El vector del plano debe contener números finitos.",
                        )
                    )
            if all(values_are_finite(vector) for _, vector in vectors):
                x_length = norm3(reference.x_axis)
                y_length = norm3(reference.y_axis)
                orthonormal = (
                    abs(x_length - 1.0) <= EPS
                    and abs(y_length - 1.0) <= EPS
                    and abs(dot3(reference.x_axis, reference.y_axis)) <= EPS
                )
                if not orthonormal:
                    diagnostics.append(
                        _diagnostic(
                            "PLANE_BASIS_INVALID",
                            path,
                            "Los ejes del plano deben ser unitarios y perpendiculares.",
                        )
                    )
        elif isinstance(reference, AxisReference):
            if not values_are_finite(reference.origin):
                diagnostics.append(
                    _diagnostic(
                        "NUMBER_NOT_FINITE",
                        f"{path}.origin",
                        "El origen del eje debe contener números finitos.",
                    )
                )
            if not values_are_finite(reference.direction):
                diagnostics.append(
                    _diagnostic(
                        "NUMBER_NOT_FINITE",
                        f"{path}.direction",
                        "La dirección del eje debe contener números finitos.",
                    )
                )
            elif norm3(reference.direction) <= EPS:
                diagnostics.append(
                    _diagnostic(
                        "AXIS_ZERO",
                        f"{path}.direction",
                        "La dirección del eje no puede ser nula.",
                    )
                )


def _validate_sketch(
    sketch: Sketch,
    index: int,
    references: dict[str, Any],
    plane_by_id: dict[str, PlaneReference],
    parameters: dict[str, Parameter],
    diagnostics: list[Diagnostic],
) -> None:
    path = f"sketches[{index}]"
    if sketch.plane_id not in references:
        diagnostics.append(
            _diagnostic(
                "SKETCH_PLANE_MISSING",
                f"{path}.plane_id",
                f"El plano '{sketch.plane_id}' no existe.",
            )
        )
    elif sketch.plane_id not in plane_by_id:
        diagnostics.append(
            _diagnostic(
                "SKETCH_PLANE_INVALID",
                f"{path}.plane_id",
                f"La referencia '{sketch.plane_id}' no es un plano.",
            )
        )

    entities = _index_by_id(sketch.entities, f"{path}.entities", diagnostics)

    for constraint_index, constraint in enumerate(sketch.constraints):
        constraint_path = f"{path}.constraints[{constraint_index}]"
        if isinstance(constraint, ClosedLoopConstraint):
            for entity_index, entity_id in enumerate(constraint.entity_ids):
                if entity_id not in entities:
                    diagnostics.append(
                        _diagnostic(
                            "CONSTRAINT_ENTITY_MISSING",
                            f"{constraint_path}.entity_ids[{entity_index}]",
                            f"La entidad '{entity_id}' no existe en el croquis.",
                        )
                    )
        elif isinstance(constraint, CoincidentAxisConstraint):
            if constraint.entity_id not in entities:
                diagnostics.append(
                    _diagnostic(
                        "CONSTRAINT_ENTITY_MISSING",
                        f"{constraint_path}.entity_id",
                        f"La entidad '{constraint.entity_id}' no existe en el croquis.",
                    )
                )
            reference = references.get(constraint.reference_id)
            if reference is None:
                diagnostics.append(
                    _diagnostic(
                        "CONSTRAINT_REFERENCE_MISSING",
                        f"{constraint_path}.reference_id",
                        f"La referencia '{constraint.reference_id}' no existe.",
                    )
                )
            elif not isinstance(reference, AxisReference):
                diagnostics.append(
                    _diagnostic(
                        "CONSTRAINT_REFERENCE_INVALID",
                        f"{constraint_path}.reference_id",
                        f"La referencia '{constraint.reference_id}' no es un eje.",
                    )
                )

    for dimension_index, dimension in enumerate(sketch.dimensions):
        dimension_path = f"{path}.dimensions[{dimension_index}]"
        if not values_are_finite(dimension.from_point + dimension.to_point):
            diagnostics.append(
                _diagnostic(
                    "COORDINATE_NOT_FINITE",
                    dimension_path,
                    "Los puntos de la dimensión deben ser finitos.",
                )
            )
        if dimension.expression is not None:
            diagnostics.append(
                _diagnostic(
                    "DIMENSION_EXPRESSION_UNSUPPORTED",
                    f"{dimension_path}.expression",
                    (
                        "La resolución de expresiones no está soportada en esta "
                        "iteración; usar una referencia a parámetro."
                    ),
                )
            )
        if dimension.parameter is not None:
            parameter = parameters.get(dimension.parameter)
            if parameter is None:
                diagnostics.append(
                    _diagnostic(
                        "DIMENSION_PARAMETER_MISSING",
                        f"{dimension_path}.parameter",
                        f"El parámetro '{dimension.parameter}' no existe.",
                    )
                )
            else:
                _validate_dimension_length(
                    dimension,
                    dimension_path,
                    parameter,
                    diagnostics,
                )
        elif dimension.expression is None:
            diagnostics.append(
                _diagnostic(
                    "DIMENSION_VALUE_MISSING",
                    dimension_path,
                    "La dimensión debe referenciar un parámetro o una expresión.",
                )
            )

    _validate_sketch_geometry(sketch, index, diagnostics)


def _validate_dimension_length(
    dimension: Dimension,
    path: str,
    parameter: Parameter,
    diagnostics: list[Diagnostic],
) -> None:
    if parameter.quantity != "length" or parameter.unit != "mm":
        diagnostics.append(
            _diagnostic(
                "UNIT_MISMATCH",
                f"{path}.parameter",
                (
                    f"La dimensión de distancia requiere un parámetro de "
                    f"magnitud length en mm; '{parameter.quantity}/{parameter.unit}' "
                    "no es válido."
                ),
            )
        )
        return
    if not decimal_is_finite(parameter.value):
        return
    if not values_are_finite(dimension.from_point + dimension.to_point):
        return

    start_x = Decimal(str(dimension.from_point[0]))
    start_y = Decimal(str(dimension.from_point[1]))
    end_x = Decimal(str(dimension.to_point[0]))
    end_y = Decimal(str(dimension.to_point[1]))
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    length = (delta_x * delta_x + delta_y * delta_y).sqrt()

    if abs(length - parameter.value) > DIMENSION_LENGTH_TOLERANCE:
        diagnostics.append(
            _diagnostic(
                "DIMENSION_LENGTH_MISMATCH",
                path,
                (
                    f"La longitud geométrica {length} no coincide con el "
                    f"parámetro '{dimension.parameter}' ({parameter.value} mm)."
                ),
            )
        )


def _validate_sketch_geometry(
    sketch: Sketch,
    index: int,
    diagnostics: list[Diagnostic],
) -> None:
    path = f"sketches[{index}]"
    if not sketch.entities:
        diagnostics.append(
            _diagnostic(
                "SKETCH_EMPTY",
                path,
                "El croquis debe contener al menos una línea.",
            )
        )
        return

    all_finite = True
    for entity_index, entity in enumerate(sketch.entities):
        if not values_are_finite(entity.start + entity.end):
            diagnostics.append(
                _diagnostic(
                    "COORDINATE_NOT_FINITE",
                    f"{path}.entities[{entity_index}]",
                    "Los extremos de la línea deben ser finitos.",
                )
            )
            all_finite = False
    if not all_finite:
        return

    segments = [(entity.start, entity.end) for entity in sketch.entities]
    valid_segments: list[tuple[int, tuple[float, float], tuple[float, float]]] = []
    for entity_index, (start, end) in enumerate(segments):
        if norm2(sub2(end, start)) <= EPS:
            diagnostics.append(
                _diagnostic(
                    "SEGMENT_ZERO_LENGTH",
                    f"{path}.entities[{entity_index}]",
                    "El segmento debe tener longitud mayor que cero.",
                )
            )
        else:
            valid_segments.append((entity_index, start, end))

    degrees: dict[tuple[float, float], int] = {}
    for start, end in segments:
        for point in (start, end):
            key = point_key(point)
            degrees[key] = degrees.get(key, 0) + 1

    invalid_endpoints = [
        (key, degree) for key, degree in degrees.items() if degree != 2
    ]
    if invalid_endpoints:
        for key, degree in invalid_endpoints:
            diagnostics.append(
                _diagnostic(
                    "SKETCH_NOT_CLOSED",
                    path,
                    (
                        f"El punto {key} tiene grado {degree}; un único bucle "
                        "cerrado exige grado 2 en cada extremo."
                    ),
                )
            )
    elif not _graph_is_connected(segments):
        diagnostics.append(
            _diagnostic(
                "SKETCH_DISCONNECTED",
                path,
                "El croquis contiene más de un bucle o componentes desconectados.",
            )
        )

    reported_pairs: set[tuple[int, int]] = set()
    for first in range(len(valid_segments)):
        first_index, first_start, first_end = valid_segments[first]
        first_keys = {point_key(first_start), point_key(first_end)}
        for second in range(first + 1, len(valid_segments)):
            second_index, second_start, second_end = valid_segments[second]
            second_keys = {
                point_key(second_start),
                point_key(second_end),
            }
            shares_endpoint = bool(first_keys & second_keys)
            if shares_endpoint:
                intersects = collinear_overlap(
                    first_start,
                    first_end,
                    second_start,
                    second_end,
                )
            else:
                intersects = segments_intersect(
                    first_start,
                    first_end,
                    second_start,
                    second_end,
                )
            if intersects:
                pair = (min(first_index, second_index), max(first_index, second_index))
                if pair in reported_pairs:
                    continue
                reported_pairs.add(pair)
                diagnostics.append(
                    _diagnostic(
                        "SKETCH_SELF_INTERSECTION",
                        f"{path}.entities[{second_index}]",
                        (
                            "Los segmentos se intersecan fuera de una unión "
                            "adyacente permitida."
                        ),
                    )
                )


def _graph_is_connected(
    segments: Sequence[tuple[tuple[float, float], tuple[float, float]]],
) -> bool:
    adjacency: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for start, end in segments:
        start_key = point_key(start)
        end_key = point_key(end)
        adjacency.setdefault(start_key, set())
        adjacency.setdefault(end_key, set())
        if start_key != end_key:
            adjacency[start_key].add(end_key)
            adjacency[end_key].add(start_key)
    if not adjacency:
        return False
    pending = [next(iter(adjacency))]
    visited: set[tuple[float, float]] = set()
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        pending.extend(adjacency[node] - visited)
    return len(visited) == len(adjacency)


def _validate_feature(
    feature: ExtrudeFeature | RevolveFeature,
    index: int,
    references: dict[str, Any],
    sketch_by_id: dict[str, Sketch],
    plane_by_id: dict[str, PlaneReference],
    axis_by_id: dict[str, AxisReference],
    diagnostics: list[Diagnostic],
) -> None:
    path = f"features[{index}]"
    sketch = sketch_by_id.get(feature.sketch_id)
    if sketch is None:
        diagnostics.append(
            _diagnostic(
                "FEATURE_SKETCH_MISSING",
                f"{path}.sketch_id",
                f"El croquis '{feature.sketch_id}' no existe.",
            )
        )

    if isinstance(feature, ExtrudeFeature):
        if not decimal_is_finite(feature.distance):
            diagnostics.append(
                _diagnostic(
                    "NUMBER_NOT_FINITE",
                    f"{path}.distance",
                    "La distancia de extrusión debe ser finita.",
                )
            )
        elif feature.distance <= 0:
            diagnostics.append(
                _diagnostic(
                    "EXTRUDE_DISTANCE_NOT_POSITIVE",
                    f"{path}.distance",
                    "La distancia de extrusión debe ser mayor que cero.",
                )
            )
        return

    axis = axis_by_id.get(feature.axis_id)
    if axis is None:
        if feature.axis_id in references:
            diagnostics.append(
                _diagnostic(
                    "FEATURE_AXIS_INVALID",
                    f"{path}.axis_id",
                    f"La referencia '{feature.axis_id}' no es un eje.",
                )
            )
        else:
            diagnostics.append(
                _diagnostic(
                    "FEATURE_AXIS_MISSING",
                    f"{path}.axis_id",
                    f"El eje '{feature.axis_id}' no existe.",
                )
            )
    if not decimal_is_finite(feature.angle):
        diagnostics.append(
            _diagnostic(
                "NUMBER_NOT_FINITE",
                f"{path}.angle",
                "El ángulo de revolución debe ser finito.",
            )
        )
    elif feature.angle <= 0 or feature.angle > Decimal("360"):
        diagnostics.append(
            _diagnostic(
                "REVOLVE_ANGLE_OUT_OF_RANGE",
                f"{path}.angle",
                "El ángulo de revolución debe estar en (0, 360].",
            )
        )

    if (
        sketch is None
        or axis is None
        or norm3(axis.direction) <= EPS
        or not values_are_finite(axis.origin)
        or not values_are_finite(axis.direction)
    ):
        return

    plane = plane_by_id.get(sketch.plane_id)
    if plane is None:
        return

    normal = plane_normal(plane.x_axis, plane.y_axis)
    if norm3(normal) <= EPS:
        return

    if not point_lies_in_plane(axis.origin, plane.origin, normal) or not (
        direction_lies_in_plane(axis.direction, normal)
    ):
        diagnostics.append(
            _diagnostic(
                "REVOLVE_AXIS_NOT_IN_PLANE",
                path,
                "El eje de revolución debe estar contenido en el plano del croquis.",
            )
        )
        return

    axis_origin_2d = project_point_to_plane(
        axis.origin,
        plane.origin,
        plane.x_axis,
        plane.y_axis,
    )
    axis_direction_2d = (
        dot3(axis.direction, plane.x_axis),
        dot3(axis.direction, plane.y_axis),
    )
    if norm2(axis_direction_2d) <= EPS:
        diagnostics.append(
            _diagnostic(
                "REVOLVE_AXIS_NOT_IN_PLANE",
                path,
                "El eje de revolución no tiene dirección válida en el plano.",
            )
        )
        return

    if not all(
        values_are_finite(entity.start + entity.end)
        for entity in sketch.entities
    ):
        return

    segments = [(entity.start, entity.end) for entity in sketch.entities]
    if axis_profile_crosses(segments, axis_origin_2d, axis_direction_2d):
        diagnostics.append(
            _diagnostic(
                "REVOLVE_PROFILE_CROSSES_AXIS",
                path,
                "El perfil cruza el eje de revolución.",
            )
        )


def _validate_tolerance(
    tolerance: Tolerance | None,
    path: str,
    diagnostics: list[Diagnostic],
) -> None:
    if tolerance is None or tolerance.kind == "none":
        return
    if tolerance.kind == "symmetric":
        if (
            tolerance.value is None
            or not decimal_is_finite(tolerance.value)
            or tolerance.value < 0
        ):
            diagnostics.append(
                _diagnostic(
                    "TOLERANCE_INVALID",
                    f"{path}.value",
                    "La tolerancia simétrica requiere un valor finito no negativo.",
                )
            )
    elif tolerance.kind == "range":
        lower = tolerance.lower
        upper = tolerance.upper
        if (
            lower is None
            or upper is None
            or not decimal_is_finite(lower)
            or not decimal_is_finite(upper)
            or lower > upper
        ):
            diagnostics.append(
                _diagnostic(
                    "TOLERANCE_INVALID",
                    path,
                    "La tolerancia por rango requiere límites finitos y ordenados.",
                )
            )
    elif tolerance.kind == "iso_fit":
        if not tolerance.designation:
            diagnostics.append(
                _diagnostic(
                    "TOLERANCE_INVALID",
                    f"{path}.designation",
                    "La tolerancia ISO requiere una designación.",
                )
            )
