# Demo walkthrough: Google ADK consumes Databricks through A2A

## What this demonstrates

A Google-hosted agentic platform stays in control. Databricks publishes a
standards-based A2A Agent Card and JSON-RPC interface. Google ADK discovers that
interface and delegates work without embedding Databricks MCP, Genie, Unity
Catalog, or Model Serving APIs in the Google orchestrator.

```text
Google ADK + Gemini
        |
        | A2A: discover card, delegate task, receive answer
        v
Databricks App (A2A provider + App telemetry)
        |
        +-- Unity Gateway model service -> Databricks-hosted model
        +-- Unity Gateway DBSQL MCP -> Unity Catalog function
```

The bundle also deploys a visual A2A client App for walking through the flow. It
uses the same standards-based discovery and JSON-RPC flow as an external client,
while displaying each observed stage and the architecture.

## Prepare the demo

1. Confirm both Apps are running:

   ```bash
   databricks apps get <provider-app-name> \
     --profile <profile> --output json
   databricks apps get <client-app-name> \
     --profile <profile> --output json
   ```

2. Confirm the Google-side identity has `CAN_USE` on the App. For the local
   demo, this is the user represented by the selected CLI profile. For a
   Google Cloud deployment, grant the Databricks OAuth service principal used
   by the orchestrator.

3. Open the visual client and rehearse the flow:

   Retrieve the URL with `databricks apps get <client-app-name>`.

   Click **Discover services** first. Point out that the capabilities and
   JSON-RPC URL came from the remote Agent Card. Select **Run Unity Catalog
   functions**, send the shipping-quote prompt, and walk through the execution
   trace. Then ask it to describe A2A: the tool-backed capability explicitly
   declines because no suitable tool can answer. Select the foundation
   model capability and repeat the question to show the intentional difference.

4. Run capability discovery from the Google side:

   ```bash
   cd src/google-adk-consumer
   DATABRICKS_A2A_APP_URL=<provider-app-url> \
   DATABRICKS_PROFILE=<profile> \
   UV_NATIVE_TLS=1 uv run --native-tls \
     --with-requirements requirements.txt \
     python -m google_adk_consumer.discover
   ```

   Point out the advertised model-service and UC-function skills and the JSON-RPC interface URL. If Genie is enabled, it appears as a third skill. This
   proves discovery happens through the A2A card rather than prior knowledge in
   the Google agent.

5. Start the Google ADK UI:

   ```bash
   cd src/google-adk-consumer
   GOOGLE_GENAI_USE_VERTEXAI=TRUE \
   GOOGLE_CLOUD_PROJECT=<gcp-project> \
   GOOGLE_CLOUD_LOCATION=<gcp-region> \
   DATABRICKS_A2A_APP_URL=<provider-app-url> \
   DATABRICKS_PROFILE=<profile> \
   UV_NATIVE_TLS=1 uv run --native-tls \
     --with-requirements requirements.txt \
     adk web .
   ```

## Live sequence

Use prompts tied to the actual configured Genie space and UC function.

1. Discovery:

   > What capabilities can the Databricks enterprise services agent provide?

2. UC-function-backed action:

   > Ask Databricks for a shipping quote from Boston to Chicago for 25 kilograms.

3. Capability boundary:

   > Describe the A2A protocol in a short paragraph.

   With the UC-function capability selected, the visual client should receive
   an explicit capability-mismatch response. With the foundation-model
   capability selected, it should receive a direct model answer.

4. Optional Genie-backed analytics:

   > Delegate to Databricks and answer: `<question grounded in the Genie space>`.

5. Explain the boundary:

   - Google Gemini chose and delegated to a remote sub-agent.
   - The only cross-platform contract was A2A.
   - Databricks resolved its own tools behind the boundary.
   - App telemetry captured the A2A request and routing decision.
   - Unity Gateway captured the downstream model and MCP interactions.
   - The Google orchestrator did not receive Databricks credentials for internal
     services, table grants, MCP tool definitions, or function implementation.

## Production authentication

The local demo uses a named Databricks CLI OAuth profile. In Google Cloud,
store the Databricks OAuth service-principal values in Secret Manager and inject
`DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET` into
the ADK runtime. `DatabricksOAuth` uses the same SDK credential discovery and
attaches a short-lived token to both Agent Card and A2A JSON-RPC requests.

Do not pass the end user's Databricks token through Google unless the deployment
requires user-level Unity Catalog enforcement. This sample uses a
service identity at the A2A boundary and the Databricks App service principal
for internal Databricks resources.

## Expected proof

The demo is successful when all of these are visible:

- Google fetches the Databricks Agent Card.
- The card describes capabilities and the standard JSON-RPC interface.
- Google ADK delegates to `databricks_enterprise_services`.
- A Databricks-backed answer returns through A2A.
- The provider request is visible in the App telemetry tables.
- The model and MCP calls are visible in Unity Gateway traces.
- Changing the internal Databricks implementation does not require changing the
  Google orchestrator's protocol integration.
