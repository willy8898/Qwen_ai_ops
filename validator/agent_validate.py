"""Shared, narrow validation-invocation logic for agent-facing wrappers.

Both optional-advanced-mcp/server.py (MCP tool, for interactive sessions /
future qwen-code versions that wire MCP into headless mode) and
run_validation.py (plain CLI wrapper, for today's headless `qwen -p` agent
runs) import this module rather than each re-implementing the same
argv-construction and safety checks.

The point of routing through here instead of letting the agent build a
validate_config.py invocation itself: the underlying script takes many flags
(--schemas-dir, --service, --config, --context key=value, --json), and in
practice weaker/local models constructing that command line get it wrong in
several different ways (wrong flag, wrong argument shape, or omitting the
script path entirely). This module exposes exactly two operations with a
handful of plain fields, and always builds the subprocess argv as a list
(never a shell string), so there's no quoting/flag-ordering for the model to
get wrong.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "validator" / "schemas"
VALIDATE_SCRIPT = REPO_ROOT / "validator" / "validate_config.py"


def discover_services() -> list[str]:
    return sorted(
        p.name[: -len(".schema.yaml")]
        for p in SCHEMAS_DIR.glob("*.schema.yaml")
        if p.name.endswith(".schema.yaml")
    )


def _resolve_config_path(config_path: str) -> Path:
    """Resolve config_path relative to the repo root and reject escapes."""
    candidate = (REPO_ROOT / config_path).resolve()
    if REPO_ROOT not in candidate.parents and candidate != REPO_ROOT:
        raise ValueError(
            f"config_path must stay inside the project ({REPO_ROOT}); "
            f"got a path that resolves to {candidate}"
        )
    return candidate


def run_validate_config(service: str, config_path: str, context: dict[str, str] | None = None) -> dict:
    """Validate one config file against its service's schema.

    Returns a dict with "passed" (bool) and either "results" (normal
    validate_config.py --json output) or "errors" (for problems with the
    arguments themselves, e.g. an unknown service or an out-of-repo path).
    """
    known_services = discover_services()
    if service not in known_services:
        return {
            "passed": False,
            "errors": [
                {
                    "path": "(service argument)",
                    "code": "UNKNOWN_SERVICE",
                    "message": f"'{service}' is not a known service.",
                    "current_value": service,
                    "suggestion": f"Pick one of: {known_services}",
                }
            ],
        }

    try:
        resolved_config = _resolve_config_path(config_path)
    except ValueError as exc:
        return {
            "passed": False,
            "errors": [
                {
                    "path": "(config_path argument)",
                    "code": "INVALID_CONFIG_PATH",
                    "message": str(exc),
                    "current_value": config_path,
                    "suggestion": "Pass a path relative to the repository root, inside the repository.",
                }
            ],
        }

    if not resolved_config.is_file():
        return {
            "passed": False,
            "errors": [
                {
                    "path": "(config_path argument)",
                    "code": "CONFIG_NOT_FOUND",
                    "message": f"No such file: {resolved_config}",
                    "current_value": config_path,
                    "suggestion": "Double check the path -- did you mean a different file?",
                }
            ],
        }

    argv = [
        sys.executable,
        str(VALIDATE_SCRIPT),
        "--schemas-dir",
        str(SCHEMAS_DIR),
        "--service",
        service,
        "--config",
        str(resolved_config),
        "--json",
    ]
    for key, value in (context or {}).items():
        argv += ["--context", f"{key}={value}"]

    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "errors": [
                {
                    "path": "(execution)",
                    "code": "VALIDATOR_TIMEOUT",
                    "message": "validate_config.py did not finish within 60s.",
                    "current_value": None,
                    "suggestion": "Report this to a human -- the validator script itself may be broken.",
                }
            ],
        }

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "passed": False,
            "errors": [
                {
                    "path": "(execution)",
                    "code": "VALIDATOR_OUTPUT_UNPARSEABLE",
                    "message": "validate_config.py did not return valid JSON.",
                    "current_value": (result.stdout + result.stderr)[:2000],
                    "suggestion": "Report this to a human with the current_value shown here.",
                }
            ],
        }
