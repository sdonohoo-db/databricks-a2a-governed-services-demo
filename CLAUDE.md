# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A reference implementation showing a Google ADK/Gemini orchestrator consuming Databricks services through A2A (`a2a-sdk` 1.0). The bundle contains two Databricks Apps: a headless provider and a visual test client. The provider emits OpenTelemetry through Databricks Apps telemetry and uses Unity Gateway for its model and MCP calls.

- `src/a2a-provider/server.py` — composes the A2A `AgentCard` and mounts JSON-RPC + agent-card routes on a `Starlette` app. The public interface URL is derived from reverse-proxy request headers; `DATABRICKS_APP_URL` is an optional local override.
- `src/a2a-provider/agent_executor.py` — bridges A2A to a Unity Gateway model service and configured MCP servers. It propagates OpenTelemetry context, adds Gateway request tags, namespaces tool names, and supports multiple MCP calls for asynchronous DBSQL polling.
- `src/a2a-client/` — a second Databricks App with a visual chat, architecture flow, Agent Card viewer, execution timeline, identity disclosure, and raw protocol metadata. Its backend binds the provider App with `CAN_USE`, resolves the provider URL using `WorkspaceClient`, and authenticates app-to-app as its own service principal.
- `google_adk_consumer/` — the customer-side proof. Google ADK uses `RemoteA2aAgent` and an authenticated A2A `ClientFactory` to discover the Databricks Agent Card and delegate through standard A2A. `discover.py` prints the card before the demo.
- `src/a2a-client/cli.py` — framework-neutral command-line validation client. Remote use requires an explicit `DATABRICKS_PROFILE`.

MCP configuration lives in `src/a2a-provider/databricks_config.py`. `MCP_BACKENDS` can select `genie`, `functions`, or both; legacy `MCP_BACKEND` remains supported.

## Local run

Governed UC functions backend:

```bash
cd src/a2a-provider
UV_NATIVE_TLS=1 databricks apps run-local \
  --prepare-environment \
  --env DATABRICKS_APP_URL=http://localhost:8000 \
  --env MCP_BACKEND=functions \
  --env MCP_SERVICE_NAME=system.ai.dbsql \
  --env UC_FUNCTION_NAME=<catalog>.<schema>.<function> \
  --env MODEL_SERVICE_NAME=<catalog>.<schema>.<model-service> \
  --env DATABRICKS_WAREHOUSE_ID=<warehouse-id> \
  -p <profile>
```

Genie backend (drop in a real `GENIE_SPACE_ID`):

```bash
cd src/a2a-provider
UV_NATIVE_TLS=1 databricks apps run-local \
  --prepare-environment \
  --env DATABRICKS_APP_URL=http://localhost:8000 \
  --env MCP_BACKEND=genie \
  --env GENIE_SPACE_ID=<space-id> \
  --env MODEL_SERVICE_NAME=<catalog>.<schema>.<model-service> \
  -p <profile>
```

The CLI builds a uv-managed `.venv` from the selected App subdirectory's `requirements.txt`, serves a proxy on `:8001`, and binds the process to `:8000`. Both ports must be free. Code edits are NOT live-reloaded.

In a separate shell, exercise the full path:

```bash
UV_SYSTEM_CERTS=1 uv run --system-certs \
  --with-requirements src/a2a-provider/requirements.txt \
  python src/a2a-client/cli.py
```

`UV_NATIVE_TLS=1` is mandatory behind the corporate Zscaler proxy — without it `uv` rejects PyPI's cert as `UnknownIssuer`. Applies to every uv-driven command in this repo, including `databricks apps run-local --prepare-environment`.

## App requirements — keep them isolated and slim

The provider and client have separate requirements files. Do not merge them: the provider needs MLflow/MCP while the visual client only needs A2A, the SDK, HTTP, and Starlette.

- `a2a-sdk[http-server]==1.0.3` — the `[http-server]` extra is required (pulls `sse-starlette`); pure `a2a-sdk` will import-fail at server start.
- `databricks-sdk[openai]>=0.57.0` — the `[openai]` extra provides the OpenAI client used with the Unity Gateway API.
- `databricks-mcp==0.9.2` — current Databricks MCP client.
- `mcp>=1.30.0,<2` — required directly by `agent_executor.py`. The upper bound
  preserves the 1.x `streamablehttp_client` API used by both this sample and
  `databricks-mcp`; 1.30.0 also includes the current 1.x transport security fix.
- OpenTelemetry dependencies provide Starlette/HTTPX instrumentation, OTLP export, and host metrics for Databricks Apps telemetry.
- Direct deps only beyond that: `mlflow-skinny`, `python-dotenv`, `httpx`, `pydantic`, `uvicorn`. Let the resolver pick versions.

## A2A 1.0 surface (do not regress to 0.2.x)

The original repo predates A2A 1.0. Common 0.2.x patterns that DO NOT work here:

- ❌ `A2AStarletteApplication(...).build(rpc_url=...)` — wrapper class is gone. This sample uses `create_jsonrpc_routes()` plus a request-aware Starlette Agent Card route.
- ❌ `AgentCard(url=..., supportsAuthenticatedExtendedCard=...)` — both fields removed. URL belongs in `supported_interfaces=[AgentInterface(protocol_binding='JSONRPC', url=...)]`; the flag moved to `AgentCapabilities.extended_agent_card`.
- ❌ `DefaultRequestHandler(agent_executor=, task_store=)` — `agent_card` is now a third required arg.
- ❌ `event_queue.enqueue_event(new_agent_text_message(...))` — `enqueue_event` is now async (`await`), and `new_agent_text_message` was renamed to `new_text_message` (in `a2a.helpers`) and takes `role=Role.ROLE_AGENT`.
- ❌ `MessageSendParams` — gone. Construct `SendMessageRequest(message=msg)` directly.
- ❌ Snake-case enum strings — `Role.ROLE_USER`/`ROLE_AGENT`, `TaskState.TASK_STATE_COMPLETED`, etc.

Types are protobuf-backed, not Pydantic. There is no `model_dump`, no arbitrary attribute assignment; iterate fields via `DESCRIPTOR.fields` or use `HasField('...')` on streaming responses.

The default agent-card path is `/.well-known/agent-card.json` (with hyphen) — older clients/docs use `agent.json`.

## Unity Gateway

`MODEL_SERVICE_NAME` is a three-part Unity Gateway model service name. The bundle creates this service, routes it to the selected `system.ai` foundation model, and enables its inference table.

The deployed functions path uses the governed `system.ai.dbsql` MCP service and passes `DATABRICKS_WAREHOUSE_ID` through MCP `_meta`. It calls `UC_FUNCTION_NAME` using SQL. MCP request and response payloads are captured by the metastore-level Unity Gateway unified trace table, not a per-service inference table.

Databricks Apps telemetry is configured on the provider App only. Logs, spans, and metrics are written to the three DAB-configured `otel_*` tables.

## Deploying to Databricks Apps

`databricks.yml` defines both Apps, the Unity Gateway model service and inference table, provider App telemetry, the model-service binding, UC Function access, and SQL warehouse access. The built-in `system.ai.dbsql` service and the metastore unified trace table are platform resources and cannot be created by this bundle. See `README.md` and `docs/governance.md` for deployment requirements.
