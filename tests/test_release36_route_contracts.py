import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "app" / "routes" / "decisions.py"
MODELS_FILE = ROOT / "app" / "models.py"


def test_decisions_response_models_are_imported_and_defined():
    route_tree = ast.parse(ROUTE_FILE.read_text())
    model_tree = ast.parse(MODELS_FILE.read_text())

    imported = set()
    for node in route_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "app.models":
            imported.update(alias.asname or alias.name for alias in node.names)

    defined = {
        node.name
        for node in model_tree.body
        if isinstance(node, ast.ClassDef)
    }

    response_models = []
    for node in ast.walk(route_tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "response_model" and isinstance(kw.value, ast.Name):
                    response_models.append(kw.value.id)

    assert response_models
    missing_imports = sorted(set(response_models) - imported)
    missing_definitions = sorted(set(response_models) - defined)
    assert not missing_imports, f"Route response models not imported: {missing_imports}"
    assert not missing_definitions, f"Route response models not defined in app.models: {missing_definitions}"


def test_organisation_format_request_contracts_are_imported_and_defined():
    route_text = ROUTE_FILE.read_text()
    models_text = MODELS_FILE.read_text()
    assert "OrganisationFormatResponse" in route_text
    assert "OrganisationFormatRenderRequest" in route_text
    assert "class OrganisationFormatResponse" in models_text
    assert "class OrganisationFormatRenderRequest" in models_text
