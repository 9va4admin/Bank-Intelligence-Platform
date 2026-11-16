"""workflow.logger is a standard-library logger: it rejects arbitrary keyword arguments (TypeError), so a call like
workflow.logger.error("x", batch_id=...) crashes the workflow the first time it runs. Found on the first live run of
InwardBatchIngestionWorkflow, which could therefore never complete. Use the module's structlog `log`, or extra={...}."""
import ast
from pathlib import Path

_ALLOWED = {"extra", "exc_info", "stack_info", "stacklevel"}
_WORKFLOWS = sorted(Path("modules/cts/workflows").glob("*.py")) + sorted(Path("modules/msv/workflows").glob("*.py"))


def _bad_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "logger"
                and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "workflow"):
            extra = [k.arg for k in node.keywords if k.arg not in _ALLOWED]
            if extra:
                yield f"{path}:{node.lineno} workflow.logger.{node.func.attr}(... {', '.join(extra)}=...)"


def test_no_workflow_logger_call_passes_arbitrary_keywords():
    bad = [b for p in _WORKFLOWS for b in _bad_calls(p)]
    assert not bad, "workflow.logger rejects these keyword arguments:\n" + "\n".join(bad)
