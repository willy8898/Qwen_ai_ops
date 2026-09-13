#!/usr/bin/env python3
"""MCP server exposing the config validator as two narrow, strictly-typed tools.

NOTE (2026-09-13): as of qwen-code 0.23.3, the headless (`qwen -p ...`) code
path does not connect to project-configured MCP servers at all -- confirmed
live (an approved, "Connected"-per-`qwen mcp list` server never appears in the
headless session's ToolRegistry, and `nonInteractiveCli`'s bundled dependency
chunk has zero references to MCP). So this server is not currently usable for
the unattended/headless agent workflow this project targets -- for that, see
validator/run_validation.py instead, which the agent reaches via its normal
shell tool. Keeping this MCP server around because it may become usable in a
future qwen-code release, in interactive sessions, or with a different agent
CLI that does wire MCP into headless mode.

Both this file and run_validation.py import the actual logic from
validator/agent_validate.py rather than duplicating it.
"""

import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "validator"))
from agent_validate import discover_services, run_validate_config  # noqa: E402

server = MCPServer(
    name="config-validator",
    instructions=(
        "Tools for validating service config files against their schema. "
        "Always call list_services first if you are not certain of the exact "
        "service id. Do not attempt to invoke validate_config.py yourself via "
        "a shell tool -- use validate_config here instead."
    ),
)


@server.tool()
def list_services() -> dict:
    """List the service ids that have a schema under validator/schemas/.

    Call this before validate_config if you're not sure of the exact service
    id string to pass -- do not guess it or invent one.
    """
    return {"services": discover_services()}


@server.tool()
def validate_config(service: str, config_path: str, context: dict[str, str] | None = None) -> dict:
    """Validate one config file against its service's schema.

    Args:
        service: exact service id, e.g. "service-fab-a". Must be one of the
            values returned by list_services -- if unsure, call list_services
            first rather than guessing.
        config_path: path to the config file, relative to the repository
            root (e.g. "configs/service-a/prod.yaml"). Must resolve to a path
            inside the repository.
        context: optional context params the schema requires (e.g.
            {"factory": "A"}). Only fill this in with a value the task's
            human requester explicitly gave you -- never invent or default a
            context value yourself. Omit entirely if the service has no
            context_params.

    Returns a dict with "passed" (bool) and "results"/"errors" -- the same
    structured result validate_config.py's --json mode produces. Fix issues
    per each error's "suggestion" field and call this again; do not proceed
    to opening a PR until "passed" is true.
    """
    return run_validate_config(service, config_path, context)


if __name__ == "__main__":
    server.run(transport="stdio")
