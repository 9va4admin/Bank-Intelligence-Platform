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


def test_the_authentication_service_is_given_the_database_so_sign_ins_are_recorded():
    """AuthService was built without db_pool, so no login event, no session row and (the user directory the alert bell reads) no sign-in was ever
    recorded: users who sign in through the identity provider could never be found by role. Found on the live bell check."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "AuthService"]
    assert calls and all(any(k.arg == "db_pool" for k in c.keywords) for c in calls), "AuthService(...) in main.py must be passed db_pool="


def test_the_api_watchdog_starts_and_stops_escalation_for_the_incidents_it_raises():
    """The watchdog raises incidents from the API process (the worker may be the thing that is down), so it must start their escalation itself and stop it on recovery."""
    src = MAIN.read_text(encoding="utf-8")
    assert "start_escalation" in src and "stop_escalation" in src


def test_the_alert_send_paths_are_given_the_routing_service():
    """The worker (monitor alerts) and the API watchdog both send alerts; without the routing service they would silently keep using only the flat settings."""
    root = MAIN.parents[2]
    assert "routing_service=_wd_routing" in MAIN.read_text(encoding="utf-8")
    worker = (root / "modules" / "cts" / "worker_activities.py").read_text(encoding="utf-8")
    assert '"routing_service": getattr(self, "_routing_service", None)' in worker and "routing_service=routing_service" in worker
