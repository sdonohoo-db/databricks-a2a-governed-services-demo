import hashlib
import re
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class MCPServerConfig:
    key: str
    display_name: str
    url: str


def _uc_scope(env: Mapping[str, str]) -> tuple[str | None, str | None]:
    function_name = env.get("UC_FUNCTION_NAME", "")
    if function_name:
        parts = function_name.split(".")
        if len(parts) != 3 or not all(parts):
            raise RuntimeError(
                "UC_FUNCTION_NAME must be a three-part name: catalog.schema.function."
            )
        return parts[0], parts[1]
    return env.get("UC_FUNCTIONS_CATALOG"), env.get("UC_FUNCTIONS_SCHEMA")


def build_mcp_server_configs(
    env: Mapping[str, str], workspace_host: str | None = None
) -> list[MCPServerConfig]:
    """Build one or more managed-MCP connections from environment config."""
    explicit = "MCP_BACKENDS" in env or "MCP_BACKEND" in env
    raw_backends = env.get("MCP_BACKENDS") or env.get("MCP_BACKEND", "")
    if raw_backends:
        backends = [
            item.strip().lower()
            for item in raw_backends.split(",")
            if item.strip()
        ]
    else:
        catalog, schema = _uc_scope(env)
        backends = []
        if env.get("GENIE_SPACE_ID"):
            backends.append("genie")
        if catalog and schema:
            backends.append("functions")

    unknown = sorted(set(backends) - {"genie", "functions"})
    if unknown:
        raise RuntimeError(
            f"Unknown MCP backend(s): {', '.join(unknown)}. "
            "Use 'genie', 'functions', or both."
        )
    if not backends:
        if explicit:
            raise RuntimeError("MCP_BACKEND(S) was set but did not select a backend.")
        return []

    workspace_host = (workspace_host or env.get("DATABRICKS_HOST", "")).rstrip("/")
    if not workspace_host:
        raise RuntimeError("DATABRICKS_HOST is required when an MCP backend is enabled.")

    configs: list[MCPServerConfig] = []
    for backend in dict.fromkeys(backends):
        if backend == "genie":
            space_id = env.get("GENIE_SPACE_ID")
            if not space_id:
                raise RuntimeError("The genie backend requires GENIE_SPACE_ID.")
            configs.append(
                MCPServerConfig(
                    key="genie",
                    display_name="Databricks Genie",
                    url=f"{workspace_host}/api/2.0/mcp/genie/{space_id}",
                )
            )
        else:
            catalog, schema = _uc_scope(env)
            if not catalog or not schema:
                raise RuntimeError(
                    "The functions backend requires UC_FUNCTION_NAME or both "
                    "UC_FUNCTIONS_CATALOG and UC_FUNCTIONS_SCHEMA."
                )
            configs.append(
                MCPServerConfig(
                    key="functions",
                    display_name=f"Unity Catalog functions ({catalog}.{schema})",
                    url=f"{workspace_host}/api/2.0/mcp/functions/{catalog}/{schema}",
                )
            )
    return configs


def qualified_tool_name(server_key: str, tool_name: str) -> str:
    """Return a collision-safe OpenAI function name of at most 64 chars."""
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", f"{server_key}__{tool_name}")
    if len(normalized) <= 64:
        return normalized
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:10]
    return f"{normalized[:53]}_{digest}"


def public_app_url(
    env: Mapping[str, str],
    headers: Mapping[str, str] | None = None,
    request_scheme: str = "http",
) -> str:
    """Return the configured URL or derive it from reverse-proxy headers."""
    app_url = env.get("DATABRICKS_APP_URL", "").rstrip("/")
    if app_url:
        return app_url

    headers = headers or {}
    host = headers.get("x-forwarded-host") or headers.get("host")
    if host:
        scheme = headers.get("x-forwarded-proto") or request_scheme
        # Proxies may append comma-separated forwarding hops.
        return f"{scheme.split(',')[0].strip()}://{host.split(',')[0].strip()}"

    raise RuntimeError(
        "Unable to determine the public App URL. Set DATABRICKS_APP_URL for "
        "local execution or provide Host/X-Forwarded-Host request headers."
    )
