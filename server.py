import os

import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)

from agent_executor import DatabricksMCPAgentExecutor
from databricks_config import build_mcp_server_configs, public_app_url

load_dotenv()


CARD_URL = "/api/.well-known/agent-card.json"
RPC_URL = "/api/a2a"


def _agent_skills() -> list[AgentSkill]:
    """Describe every Databricks capability configured for this deployment."""
    skills = [
        AgentSkill(
            id="databricks-foundation-model",
            name="Databricks foundation-model conversation",
            description=(
                "Answers general text questions with the configured Databricks "
                "foundation-model serving endpoint."
            ),
            tags=["llm", "model-serving", "databricks"],
            examples=["Explain how A2A and MCP complement each other."],
        )
    ]
    configured = {config.key for config in build_mcp_server_configs(os.environ)}
    if "genie" in configured:
        skills.append(
            AgentSkill(
                id="genie",
                name="Query a Databricks Genie space",
                description=(
                    "Answers natural-language questions against the Databricks "
                    "Genie space configured via GENIE_SPACE_ID."
                ),
                tags=["genie", "mcp", "databricks"],
                examples=["List top 3 distribution centers."],
            )
        )
    if "functions" in configured:
        skills.append(
            AgentSkill(
                id="uc-tools",
                name="Run Unity Catalog functions",
                description=(
                    "Invokes authorized UC functions through the "
                    "Databricks-managed MCP server."
                ),
                tags=["unity-catalog", "functions", "mcp", "databricks"],
                examples=[
                    "Give me a governed shipping quote from Boston to Chicago for 25 kilograms."
                ],
            )
        )
    return skills


def build_app() -> Starlette:
    public_url = public_app_url(os.environ)

    agent_card = AgentCard(
        name="databricks-enterprise-services",
        description=(
            "A standards-based A2A interface through which external enterprise "
            "agents can consume governed Databricks AI, data, and function services."
        ),
        version="1.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=_agent_skills(),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=f"{public_url}{RPC_URL}",
            )
        ],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=DatabricksMCPAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    routes = [
        *create_agent_card_routes(agent_card, card_url=CARD_URL),
        *create_jsonrpc_routes(request_handler, rpc_url=RPC_URL),
    ]
    return Starlette(routes=routes)


app = build_app()


if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
