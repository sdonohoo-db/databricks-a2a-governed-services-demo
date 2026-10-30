# Databricks services exposed through A2A

## Overview

This example demonstrates how an enterprise agent running outside
Databricks—for example, a Google ADK/Gemini orchestrator—can discover and use
Databricks capabilities through the open A2A protocol.

The external client retrieves a standard A2A Agent Card, evaluates the
advertised capabilities, and delegates a task over JSON-RPC. Databricks keeps
Model Serving, managed MCP, Unity Catalog functions, credentials, and execution
details behind the A2A boundary.

The bundle deploys two Databricks Apps:

1. **A2A provider** — publishes the Agent Card and JSON-RPC endpoint, invokes a
   Databricks foundation model, and can call Unity Catalog functions through a
   Databricks-managed MCP server.
2. **A2A client simulator** — behaves as a Google-hosted A2A client. It makes
   capability discovery and delegation visible, displays the Agent Card, and
   explains the protocol flow.

The foundation-model capability has a limited conversational scope covering
A2A, MCP, Databricks AI and agent services, and enterprise agent architecture.
The sample Unity Catalog function provides shipping quotes.

This demo builds on Wenwen Xie's
[Connecting A2A and MCP on Databricks Apps](https://www.linkedin.com/pulse/connecting-a2a-mcp-databricks-apps-practical-example-wenwen-xie-iuzye/)
article and the accompanying
[databricks_a2a_mcp_connection repository](https://github.com/vivian-xie-db/databricks_a2a_mcp_connection).

## Architecture

![A2A architecture](docs/a2a-architecture.png)

## Pre-deployment requirements

### 1. Confirm the catalog and schema

Confirm that the target Unity Catalog catalog and schema exist and that you can
create a function in that schema.

### 2. Create the function

Create the Unity Catalog function used by the App:

```shell
databricks experimental aitools tools query \
  "$(python3 setup/render_demo_function.py \
      --function-name "<catalog>.<schema>.<function>")" \
  --profile <profile>
```

The renderer applies the supplied three-part name to the sample shipping-quote
function in `setup/create_demo_function.sql`. Use the same function name for
`uc_function_name` during deployment.

## Deploy

Supply workspace-specific values directly to the bundle command. The App uses
the Databricks-hosted foundation model endpoint selected through
`llm_endpoint_name`.

```bash
databricks apps deploy -t dev \
  --var="provider_app_name=<provider-app-name>" \
  --var="client_app_name=<client-app-name>" \
  --var="uc_function_name=<catalog>.<schema>.<function>" \
  --var="llm_endpoint_name=<chat-serving-endpoint>" \
  --profile <profile>
```

To exercise the provider using the Google A2A SDK without the visual client, see
[Test with the framework-neutral A2A client](docs/framework-neutral-client.md).
