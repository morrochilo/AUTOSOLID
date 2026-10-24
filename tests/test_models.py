from decimal import Decimal

import pytest
from pydantic import ValidationError

from autosolid.cad import CadSpec, Dimension, Parameter, validate_spec
from tests.builders import D, extrude_spec, make_parameter, revolve_spec


def test_valid_specs_have_no_diagnostics():
    assert validate_spec(revolve_spec()) == []
    assert validate_spec(extrude_spec()) == []


def test_models_are_immutable():
    spec = revolve_spec()
    with pytest.raises(ValidationError):
        spec.project_id = "other"
    with pytest.raises(ValidationError):
        spec.parameters["length"].value = D("90.000")


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        CadSpec(project_id="prj_test", unexpected=True)
    with pytest.raises(ValidationError):
        Parameter(
            value=D("10.000"),
            unit="mm",
            origin="user_supplied",
            unexpected=True,
        )


def test_unknown_or_non_canonical_units_are_rejected():
    with pytest.raises(ValidationError):
        make_parameter("10.000", unit="in")
    with pytest.raises(ValidationError):
        CadSpec.model_validate(
            {
                "project_id": "prj_test",
                "units": {"length": "in", "angle": "deg"},
            }
        )


def test_decimal_precision_is_preserved_in_json_round_trip():
    spec = revolve_spec()
    payload = spec.model_dump_json()

    assert '"50.000"' in payload
    assert '"80.000"' in payload
    assert '"from"' in payload
    assert '"to"' in payload

    restored = CadSpec.model_validate_json(payload)
    assert restored == spec
    assert str(restored.parameters["outer_diameter"].value) == "50.000"


def test_dimension_alias_is_accepted_and_serialised():
    dimension = Dimension(**{"from": (0.0, 0.0), "to": (10.0, 0.0)}, parameter="p")
    payload = dimension.model_dump_json()
    assert '"from":[0.0,0.0]' in payload
    assert '"to":[10.0,0.0]' in payload


def test_invalid_schema_mapping_returns_schema_diagnostic():
    diagnostics = validate_spec({"project_id": "prj_test", "unexpected": 1})
    assert [diagnostic.code for diagnostic in diagnostics] == ["SCHEMA_INVALID"]
    assert diagnostics[0].path == "unexpected"


def test_validate_spec_accepts_mapping_without_raising():
    spec = revolve_spec()
    diagnostics = validate_spec(spec.model_dump(mode="json"))
    assert diagnostics == []


def test_parameter_decimal_is_kept_exactly():
    parameter = make_parameter("50.000")
    assert isinstance(parameter.value, Decimal)
    assert str(parameter.value) == "50.000"
