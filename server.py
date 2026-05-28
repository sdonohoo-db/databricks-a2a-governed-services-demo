import os

import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette

from a2a.server.agent_execution import AgentExecutor  # noqa: F401  (typing aid)
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)

from agent_executor import UCToolsAgentExecutor

load_dotenv()


CARD_URL = "/api/.well-known/agent-card.json"
RPC_URL = "/api/a2a"


def build_app() -> Starlette:
    public_url = os.environ["DATABRICKS_APP_URL"].rstrip("/")

    skill = AgentSkill(
        id="uc-tools",
        name="Run Unity Catalog functions",
        description="Invokes UC functions registered under eva_catalog_dev.mcp_tools via the Databricks-managed MCP server.",
        tags=["unity-catalog", "mcp", "databricks"],
        examples=[
            "Compare top-rated businesses in Saint Paul.",
            "Fetch the markdown content of https://databricks.com/.",
        ],
    )

    agent_card = AgentCard(
        name="uc-tools-agent",
        description="A2A agent backed by Databricks UC Functions MCP server.",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=f"{public_url}{RPC_URL}",
            )
        ],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=UCToolsAgentExecutor(),
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
