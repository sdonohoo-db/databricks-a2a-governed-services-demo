# Customer Demo: Google ADK consumes Databricks through A2A

## Message to land

The customer's Google agentic platform stays in control. Databricks publishes a
standards-based A2A Agent Card and JSON-RPC interface. Google ADK discovers that
interface and delegates work without embedding Databricks MCP, Genie, Unity
Catalog, or Model Serving APIs in the Google orchestrator.

```text
Google ADK + Gemini
        |
        | A2A: discover card, delegate task, receive answer
        v
Databricks App (A2A provider)
        |
        +-- Databricks Model Serving
        +-- Managed MCP -> Unity Catalog functions
        +-- Optional managed MCP -> Genie
```

## Before the meeting

1. Confirm the App is running:

   ```bash
   databricks apps get databricks-a2a-elements \
     --profile fevm-sdonohoo-demotest --output json
   ```

2. Confirm the Google-side identity has `CAN_USE` on the App. For the local
   demo, this is the user represented by `fevm-sdonohoo-demotest`. For a Google
   Cloud deployment, grant the Databricks OAuth service principal used by the
   orchestrator.

3. Run capability discovery from the Google side:

   ```bash
   DATABRICKS_A2A_APP_URL=https://databricks-a2a-elements-7474653063456586.aws.databricksapps.com \
   DATABRICKS_PROFILE=fevm-sdonohoo-demotest \
   UV_NATIVE_TLS=1 uv run --native-tls \
     --with-requirements requirements-google-adk.txt \
     python -m google_adk_consumer.discover
   ```

   Point out the advertised Model Serving and UC-function skills and the JSON-RPC interface URL. If Genie is enabled, it appears as a third skill. This
   proves discovery happens through the A2A card rather than prior knowledge in
   the Google agent.

4. Start the Google ADK UI:

   ```bash
   GOOGLE_GENAI_USE_VERTEXAI=TRUE \
   GOOGLE_CLOUD_PROJECT=<gcp-project> \
   GOOGLE_CLOUD_LOCATION=us-central1 \
   DATABRICKS_A2A_APP_URL=https://databricks-a2a-elements-7474653063456586.aws.databricksapps.com \
   DATABRICKS_PROFILE=fevm-sdonohoo-demotest \
   UV_NATIVE_TLS=1 uv run --native-tls \
     --with-requirements requirements-google-adk.txt \
     adk web .
   ```

## Live sequence

Use prompts tied to the actual configured Genie space and UC function.

1. Discovery:

   > What governed capabilities can the Databricks enterprise services agent provide?

2. UC-function-backed action:

   > Ask Databricks for a governed shipping quote from Boston to Chicago for 25 kilograms.

3. Optional Genie-backed analytics:

   > Delegate to Databricks and answer: `<question grounded in the Genie space>`.

4. Explain the boundary:

   - Google Gemini chose and delegated to a remote sub-agent.
   - The only cross-platform contract was A2A.
   - Databricks resolved its own governed tools behind the boundary.
   - The Google orchestrator did not receive Databricks credentials for internal
     services, table grants, MCP tool definitions, or function implementation.

## Production authentication

The local demo uses a named Databricks CLI OAuth profile. In Google Cloud,
store the Databricks OAuth service-principal values in Secret Manager and inject
`DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET` into
the ADK runtime. `DatabricksOAuth` uses the same SDK credential discovery and
attaches a short-lived token to both Agent Card and A2A JSON-RPC requests.

Do not pass the end user's Databricks token through Google unless the customer
specifically requires user-level Unity Catalog enforcement. This sample uses a
service identity at the A2A boundary and the Databricks App service principal
for internal Databricks resources.

## Expected proof

The demo is successful when all of these are visible:

- Google fetches the Databricks Agent Card.
- The card describes capabilities and the standard JSON-RPC interface.
- Google ADK delegates to `databricks_enterprise_services`.
- A Databricks-backed answer returns through A2A.
- Changing the internal Databricks implementation does not require changing the
  Google orchestrator's protocol integration.
