# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A reference implementation showing a Google ADK/Gemini orchestrator consuming governed Databricks services through A2A (`a2a-sdk` 1.0). Databricks hosts the remote A2A provider and keeps Model Serving plus managed MCP access to UC Functions (and optionally Genie) behind the protocol boundary.

- `server.py` — composes the A2A `AgentCard` and mounts JSON-RPC + agent-card routes on a `Starlette` app. The card's `supported_interfaces[0].url` is built from the required `DATABRICKS_APP_URL` env var. It advertises Model Serving plus each configured MCP capability.
- `agent_executor.py` — `DatabricksMCPAgentExecutor.execute()` is the A2A entry point. Each request is delegated synchronously (via `run_in_executor`) to `SingleTurnMCPAgent.predict()`, which discovers tools from every configured managed MCP server, namespaces tool names, calls the Databricks LLM serving endpoint, runs at most one tool call, calls the LLM a second time, and returns the assistant text. Single-turn only — no multi-step tool use.
- `google_adk_consumer/` — the customer-side proof. Google ADK uses `RemoteA2aAgent` and an authenticated A2A `ClientFactory` to discover the Databricks Agent Card and delegate through standard A2A. `discover.py` prints the card before the demo.
- `client.py` — framework-neutral A2A validation client. It resolves the card, sends one streaming request, and prints every possible response field. Remote use requires an explicit `DATABRICKS_PROFILE`.

MCP configuration lives in `databricks_config.py`. `MCP_BACKENDS` can select `genie`, `functions`, or both; legacy `MCP_BACKEND` remains supported. UC Functions can be scoped with injected `UC_FUNCTION_NAME` or legacy `UC_FUNCTIONS_CATALOG`/`UC_FUNCTIONS_SCHEMA`.

## Local run

UC functions backend (verified end-to-end on the user's DEFAULT profile against `eva_catalog_dev.mcp_tools`):

```bash
UV_NATIVE_TLS=1 databricks apps run-local \
  --prepare-environment \
  --env DATABRICKS_APP_URL=http://localhost:8000 \
  --env MCP_BACKEND=functions \
  --env UC_FUNCTIONS_CATALOG=eva_catalog_dev \
  --env UC_FUNCTIONS_SCHEMA=mcp_tools \
  -p DEFAULT
```

Genie backend (drop in a real `GENIE_SPACE_ID`):

```bash
UV_NATIVE_TLS=1 databricks apps run-local \
  --prepare-environment \
  --env DATABRICKS_APP_URL=http://localhost:8000 \
  --env MCP_BACKEND=genie \
  --env GENIE_SPACE_ID=<space-id> \
  -p DEFAULT
```

The CLI builds a uv-managed `.venv` from `requirements.txt`, mixes in its own AppKit deps (~130 packages — gradio, streamlit, shiny, dash, mlflow, etc.), serves a proxy on `:8001`, and runs `python server.py` which binds `:8000`. Both ports must be free; if startup fails silently, check `lsof -nP -iTCP:8000 -sTCP:LISTEN` for orphans from other repos. Code edits are NOT live-reloaded — kill and restart the CLI on every change.

In a separate shell, exercise the full path:

```bash
UV_NATIVE_TLS=1 uv run --native-tls python client.py
```

`UV_NATIVE_TLS=1` is mandatory behind the corporate Zscaler proxy — without it `uv` rejects PyPI's cert as `UnknownIssuer`. Applies to every uv-driven command in this repo, including `databricks apps run-local --prepare-environment`.

## requirements.txt — keep it slim

The CLI re-resolves your `requirements.txt` together with its injected AppKit deps. Over-pinning fights this and produces unsatisfiable solver errors (we hit it on `protobuf`, `mcp`, `starlette`). Only pin the things this repo actually imports plus the few must-have versions:

- `a2a-sdk[http-server]==1.0.3` — the `[http-server]` extra is required (pulls `sse-starlette`); pure `a2a-sdk` will import-fail at server start.
- `databricks-sdk[openai]>=0.57.0` — the `[openai]` extra is required because `agent_executor.py` calls `ws.serving_endpoints.get_open_ai_client()`.
- `databricks-mcp==0.9.0` — pins `mcp>=1.13`, so do not pin `mcp` separately.
- Direct deps only beyond that: `mlflow-skinny`, `python-dotenv`, `httpx`, `pydantic`, `uvicorn`. Let the resolver pick versions.

## A2A 1.0 surface (do not regress to 0.2.x)

The original repo predates A2A 1.0. Common 0.2.x patterns that DO NOT work here:

- ❌ `A2AStarletteApplication(...).build(rpc_url=...)` — wrapper class is gone. Use `create_agent_card_routes()` + `create_jsonrpc_routes()` from `a2a.server.routes`, mounted directly on `Starlette(routes=[...])`.
- ❌ `AgentCard(url=..., supportsAuthenticatedExtendedCard=...)` — both fields removed. URL belongs in `supported_interfaces=[AgentInterface(protocol_binding='JSONRPC', url=...)]`; the flag moved to `AgentCapabilities.extended_agent_card`.
- ❌ `DefaultRequestHandler(agent_executor=, task_store=)` — `agent_card` is now a third required arg.
- ❌ `event_queue.enqueue_event(new_agent_text_message(...))` — `enqueue_event` is now async (`await`), and `new_agent_text_message` was renamed to `new_text_message` (in `a2a.helpers`) and takes `role=Role.ROLE_AGENT`.
- ❌ `MessageSendParams` — gone. Construct `SendMessageRequest(message=msg)` directly.
- ❌ Snake-case enum strings — `Role.ROLE_USER`/`ROLE_AGENT`, `TaskState.TASK_STATE_COMPLETED`, etc.

Types are protobuf-backed, not Pydantic. There is no `model_dump`, no arbitrary attribute assignment; iterate fields via `DESCRIPTOR.fields` or use `HasField('...')` on streaming responses.

The default agent-card path is `/.well-known/agent-card.json` (with hyphen) — older clients/docs use `agent.json`.

## LLM endpoint

`LLM_ENDPOINT_NAME` in `agent_executor.py` must name an endpoint that exists pay-per-token on the target workspace. The DEFAULT profile (Azure `adb-6239133969168510`) does NOT host `databricks-claude-3-7-sonnet`; current default is `databricks-claude-sonnet-4-6`. List available endpoints with:

```bash
databricks serving-endpoints list -p DEFAULT --output json | \
  jq '.[] | select(.task=="llm/v1/chat" and .state.ready=="READY") | .name'
```

## Deploying to Databricks Apps

`databricks.yml` defines the deployable `demo` target for `fevm-sdonohoo-demotest`, including the concrete public App URL and least-privilege bindings for Model Serving (`CAN_QUERY`) and the demo UC function (`EXECUTE`). The `WorkspaceClient()` in the executor picks up the App service principal automatically. See `DEMO.md` for the Google-side proof sequence.

## Git remotes

- `origin` → `sdonohoo-db/databricks_a2a_mcp_connection` (the user's fork; push here)
- `upstream` → `vivian-xie-db/databricks_a2a_mcp_connection` (original sample; pull from here for upstream updates)
