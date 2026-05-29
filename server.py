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

load_dotenv()


CARD_URL = "/api/.well-known/agent-card.json"
RPC_URL = "/api/a2a"


def _backend_skill() -> AgentSkill:
    """Build a skill description that reflects the configured MCP backend."""
    backend = os.environ.get("MCP_BACKEND", "genie").lower()
    if backend == "genie":
        return AgentSkill(
            id="genie",
            name="Query a Databricks Genie space",
            description="Answers natural-language questions against the Databricks Genie space configured via GENIE_SPACE_ID.",
            tags=["genie", "mcp", "databricks"],
            examples=["List top 3 distribution centers."],
        )
    return AgentSkill(
        id="uc-tools",
        name="Run Unity Catalog functions",
        description="Invokes UC functions registered under UC_FUNCTIONS_CATALOG.UC_FUNCTIONS_SCHEMA via the Databricks-managed MCP server.",
        tags=["unity-catalog", "mcp", "databricks"],
        examples=[
            "Run a UC function that compares businesses by city.",
            "Fetch the markdown content of a URL.",
        ],
    )


def build_app() -> Starlette:
    public_url = os.environ["DATABRICKS_APP_URL"].rstrip("/")

    agent_card = AgentCard(
        name="databricks-mcp-agent",
        description="A2A agent that exposes a Databricks-managed MCP server (Genie space or UC Functions) as remote tooling.",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[_backend_skill()],
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
