"""Routes read bank settings through request.app.state.config_service. It was never assigned at startup, so every
such route (allocation claim, review queue, allocation admin, outward core, MSV) silently saw an empty config and used
its hard-coded default; allocation_mode could never leave SELF. This guards the one-line wiring in the API lifespan."""
import ast
import pathlib

MAIN = pathlib.Path(__file__).resolve().parents[3] / "apps" / "api" / "main.py"


def test_lifespan_exposes_the_config_service_on_app_state():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    found = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Attribute) and t.attr == "config_service"
                and isinstance(t.value, ast.Attribute) and t.value.attr == "state" for t in n.targets)
        and isinstance(n.value, ast.Name) and n.value.id == "config_service"
        for n in ast.walk(tree)
    )
    assert found, "main.py must set app.state.config_service = config_service during startup"
