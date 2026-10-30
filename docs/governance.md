# Governance and observability

The A2A provider uses two complementary telemetry paths:

- Databricks Apps telemetry captures the A2A HTTP interface, application logs,
  custom spans, and metrics in the configured `otel_*` Unity Catalog tables.
- Unity Gateway captures downstream model and MCP activity in its unified trace
  table. The DAB-managed model service also writes request and response payloads
  to its own inference table.

The built-in `system.ai.dbsql` MCP service is used to execute the sample Unity
Catalog function. This routes the MCP interaction through Unity Gateway. MCP
services do not have per-service inference tables; their payload-level
observability is provided by the unified trace table.

## One-time workspace setup

Enable these previews before deployment:

- Databricks Apps telemetry
- Unity Gateway Beta for `system.ai.dbsql`
- Enhanced Unity Gateway for the unified trace table

A metastore admin must set up the unified trace table once from **AI Gateway >
Govern > Traces**. This setting applies to every Unity Gateway model and MCP
service attached to the metastore and is not a DAB resource.

The A2A provider App must be able to execute `system.ai.dbsql`. If the workspace
does not inherit that access from `system.ai`, grant its service principal `USE
CATALOG` on `system`, `USE SCHEMA` on `system.ai`, and `EXECUTE` on
`system.ai.dbsql` after the App is created.

## Data produced

| Source | Tables |
|---|---|
| A2A provider App | `<telemetry_table_prefix>_otel_logs`, `_otel_spans`, `_otel_metrics` |
| Model service | `<model_inference_table_prefix>_payload` |
| Unity Gateway model and MCP services | Metastore unified trace table |

Model requests include `a2a_request_id` and `a2a_skill` request tags. The App
also records these values as OpenTelemetry span attributes so an A2A request can
be correlated with its downstream model activity.

## Resources

- [Databricks Apps observability](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/observability)
- [Unity Gateway overview](https://docs.databricks.com/aws/en/ai-gateway/)
- [Unity Gateway model services](https://docs.databricks.com/aws/en/ai-gateway/model-services)
- [Unity Gateway inference tables](https://docs.databricks.com/aws/en/ai-gateway/inference-tables)
- [Databricks-managed MCP servers](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp)
- [Unity Gateway MCP service API](https://docs.databricks.com/api/ai-gateway/v1/mcp-service)
