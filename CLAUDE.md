# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A reference implementation showing a Google ADK/Gemini orchestrator consuming Databricks services through A2A (`a2a-sdk` 1.0). The bundle contains two Databricks Apps: a headless provider and a visual test client. Databricks keeps Model Serving plus managed MCP access to UC Functions (and optionally Genie) behind the provider's protocol boundary.

- `src/a2a-provider/server.py` — composes the A2A `AgentCard` and mounts JSON-RPC + agent-card routes on a `Starlette` app. The public interface URL is derived from reverse-proxy request headers; `DATABRICKS_APP_URL` is an optional local override.
- `src/a2a-provider/agent_executor.py` — bridges A2A to Model Serving and every configured managed MCP server. It namespaces tool names and runs at most one tool call per request.
- `src/a2a-client/` — a second Databricks App with a visual chat, architecture flow, Agent Card viewer, execution timeline, identity disclosure, and raw protocol metadata. Its backend binds the provider App with `CAN_USE`, resolves the provider URL using `WorkspaceClient`, and authenticates app-to-app as its own service principal.
- `google_adk_consumer/` — the customer-side proof. Google ADK uses `RemoteA2aAgent` and an authenticated A2A `ClientFactory` to discover the Databricks Agent Card and delegate through standard A2A. `discover.py` prints the card before the demo.
- `src/a2a-client/cli.py` — framework-neutral command-line validation client. Remote use requires an explicit `DATABRICKS_PROFILE`.

MCP configuration lives in `src/a2a-provider/databricks_config.py`. `MCP_BACKENDS` can select `genie`, `functions`, or both; legacy `MCP_BACKEND` remains supported.

## Local run

UC functions backend:

```bash
cd src/a2a-provider
UV_NATIVE_TLS=1 databricks apps run-local \
  --prepare-environment \
  --env DATABRICKS_APP_URL=http://localhost:8000 \
  --env MCP_BACKEND=functions \
  --env UC_FUNCTIONS_CATALOG=<catalog> \
  --env UC_FUNCTIONS_SCHEMA=<schema> \
  --env LLM_ENDPOINT_NAME=<chat-endpoint> \
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
  --env LLM_ENDPOINT_NAME=<chat-endpoint> \
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
- `databricks-sdk[openai]>=0.57.0` — the `[openai]` extra is required because the provider executor calls `ws.serving_endpoints.get_open_ai_client()`.
- `databricks-mcp==0.9.2` — current Databricks MCP client.
- `mcp>=1.30.0,<2` — required directly by `agent_executor.py`. The upper bound
  preserves the 1.x `streamablehttp_client` API used by both this sample and
  `databricks-mcp`; 1.30.0 also includes the current 1.x transport security fix.
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

## LLM endpoint

`LLM_ENDPOINT_NAME` in `src/a2a-provider/agent_executor.py` must name a chat-capable endpoint that exists in the target workspace. It is required and has no repository default.

```bash
databricks serving-endpoints list -p <profile> --output json | \
  jq '.[] | select(.task=="llm/v1/chat" and .state.ready=="READY") | .name'
```

## Deploying to Databricks Apps

`databricks.yml` defines both Apps without workspace-specific defaults. The deployer must supply app names, a UC function FQN, and a Model Serving endpoint. The provider gets Model Serving `CAN_QUERY` and UC Function `EXECUTE`. The visual client gets provider-App `CAN_USE`; its backend resolves the bound App name to a URL and calls it with `WorkspaceClient().config.authenticate()`. See `README.md` for deployment and `DEMO.md` for the visual proof sequence.
