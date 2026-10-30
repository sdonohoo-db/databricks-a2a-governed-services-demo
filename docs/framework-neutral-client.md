# Test with the framework-neutral A2A client

The command-line client resolves the provider's Agent Card, follows the
advertised JSON-RPC interface, sends one A2A message, and prints the streamed
response.

## Prerequisites

- The A2A provider App is deployed and running.
- You know its public App URL.
- The selected Databricks CLI profile can use the provider App.
- `uv` is installed locally.

## Run against a deployed provider

Pass the provider API URL, profile, and prompt directly to the process:

```bash
A2A_BASE_URL=<provider-app-url>/api \
DATABRICKS_PROFILE=<profile> \
PROMPT="Give me a shipping quote from Boston to Chicago for 25 kilograms." \
UV_SYSTEM_CERTS=1 uv run --system-certs \
  --with-requirements src/a2a-provider/requirements.txt \
  python src/a2a-client/cli.py
```

The client obtains a short-lived Databricks OAuth token from the named profile.
It does not print or persist the token.

## Run against a local provider

When the provider is available at `http://localhost:8000`, authentication is
not added and `A2A_BASE_URL` may be omitted:

```bash
PROMPT="Explain how A2A and MCP complement each other." \
UV_SYSTEM_CERTS=1 uv run --system-certs \
  --with-requirements src/a2a-provider/requirements.txt \
  python src/a2a-client/cli.py
```

The client defaults to `http://localhost:8000/api` for local execution.
