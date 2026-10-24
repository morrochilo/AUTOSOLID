import json

from autosolid.cad import Diagnostic, cad_spec_json_schema, diagnostic_json_schema
from autosolid.cad.schema import main


def test_cad_spec_schema_exposes_expected_contract():
    schema = cad_spec_json_schema()
    assert schema["title"] == "CadSpec"
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    for expected in (
        "schema_version",
        "units",
        "sources",
        "evidence",
        "parameters",
        "references",
        "sketches",
        "features",
        "open_questions",
        "assumptions",
    ):
        assert expected in properties


def test_diagnostic_schema_is_serialisable():
    schema = diagnostic_json_schema()
    assert schema["title"] == "Diagnostic"
    diagnostic = Diagnostic(
        code="SKETCH_NOT_CLOSED",
        severity="error",
        path="sketches[0]",
        message="El croquis no está cerrado.",
    )
    payload = json.loads(diagnostic.model_dump_json())
    assert payload == {
        "code": "SKETCH_NOT_CLOSED",
        "severity": "error",
        "path": "sketches[0]",
        "message": "El croquis no está cerrado.",
    }


def test_cli_prints_schema_to_stdout(capsys):
    assert main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "CadSpec"


def test_cli_writes_only_to_explicit_path(tmp_path, capsys):
    destination = tmp_path / "cadspec.schema.json"
    assert main([str(destination)]) == 0
    written = json.loads(destination.read_text(encoding="utf-8"))
    assert written["title"] == "CadSpec"
    assert str(destination) in capsys.readouterr().out


def test_cli_rejects_extra_arguments(capsys):
    assert main(["one.json", "two.json"]) == 2
    assert "Uso:" in capsys.readouterr().err
