"""Google ADK orchestrator that consumes the Databricks agent through A2A."""

import os

import httpx
from a2a.client import ClientConfig, ClientFactory
from google.adk.agents.llm_agent import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

from .auth import DatabricksOAuth


app_url = os.environ["DATABRICKS_A2A_APP_URL"].rstrip("/")
profile = os.environ.get("DATABRICKS_PROFILE")

databricks_http_client = httpx.AsyncClient(
    auth=DatabricksOAuth(profile),
    timeout=httpx.Timeout(120),
)
databricks_a2a_client_factory = ClientFactory(
    ClientConfig(httpx_client=databricks_http_client, streaming=True)
)

databricks_agent = RemoteA2aAgent(
    name="databricks_enterprise_services",
    description=(
        "Remote Databricks specialist discovered through its A2A Agent Card. "
        "Delegate requests that need governed Databricks data, Genie analytics, "
        "Unity Catalog functions, or Databricks-hosted AI services."
    ),
    agent_card=f"{app_url}/api/.well-known/agent-card.json",
    a2a_client_factory=databricks_a2a_client_factory,
    use_legacy=True,
)

root_agent = Agent(
    name="google_enterprise_orchestrator",
    model=os.environ.get("GOOGLE_MODEL", "gemini-2.5-flash"),
    instruction=(
        "You are the customer's Google-based enterprise orchestrator. Keep normal "
        "reasoning in Google ADK, but delegate requests for governed Databricks "
        "data or services to databricks_enterprise_services. Tell the user when "
        "a result came from the remote Databricks A2A agent."
    ),
    sub_agents=[databricks_agent],
)
