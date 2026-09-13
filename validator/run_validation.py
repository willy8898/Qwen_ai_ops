#!/usr/bin/env python3
"""Agent-facing validation wrapper -- the ONLY way the agent should invoke validation.

Usage (exactly this shape, nothing else):

    python3 validator/run_validation.py <service> <config_path> [key=value ...]

Examples:

    python3 validator/run_validation.py service-fab-a configs/service-a/prod.yaml
    python3 validator/run_validation.py service-fab-a configs/service-a/prod.yaml factory=A

Do not call validator/validate_config.py directly. This wrapper takes plain
positional arguments (no --flags to get wrong) and always prints one JSON
object to stdout. Exit code 0 = passed, 1 = failed (same convention as
validate_config.py itself).
"""

import json
import sys

from agent_validate import discover_services, run_validate_config


def main() -> int:
    if len(sys.argv) < 3:
        print(
            json.dumps(
                {
                    "passed": False,
                    "errors": [
                        {
                            "path": "(arguments)",
                            "code": "USAGE_ERROR",
                            "message": "Expected: run_validation.py <service> <config_path> [key=value ...]",
                            "current_value": sys.argv[1:],
                            "suggestion": (
                                "Example: run_validation.py service-fab-a configs/service-a/prod.yaml factory=A "
                                f"-- known services: {discover_services()}"
                            ),
                        }
                    ],
                }
            )
        )
        return 1

    service, config_path, *context_pairs = sys.argv[1:]

    context: dict[str, str] = {}
    for pair in context_pairs:
        if "=" not in pair:
            print(
                json.dumps(
                    {
                        "passed": False,
                        "errors": [
                            {
                                "path": "(arguments)",
                                "code": "USAGE_ERROR",
                                "message": f"Context argument '{pair}' is not in key=value form.",
                                "current_value": pair,
                                "suggestion": "Example: factory=A",
                            }
                        ],
                    }
                )
            )
            return 1
        key, value = pair.split("=", 1)
        context[key] = value

    result = run_validate_config(service, config_path, context or None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
