import os

import uvicorn
from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_jsonrpc_routes
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
            name="Databricks interoperability advisor",
            description=(
                "Uses a Databricks foundation model to discuss A2A, MCP, "
                "Databricks AI and agent services, and enterprise agent "
                "architecture. Questions outside this conversational scope "
                "are declined."
            ),
            tags=["llm", "model-serving", "databricks"],
            examples=[
                "Explain how A2A and MCP complement each other.",
                "How can a Google-hosted agent discover Databricks capabilities?",
                "When should an enterprise use A2A instead of calling MCP directly?",
            ],
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
                    "Give me a shipping quote from Boston to Chicago for 25 kilograms.",
                    "Estimate shipping from New York to Austin for 10 kilograms.",
                    "What is the quote from Seattle to Miami for 50 kilograms?",
                ],
            )
        )
    return skills


def _agent_card(public_url: str) -> AgentCard:
    return AgentCard(
        name="databricks-enterprise-services",
        description=(
            "A standards-based A2A interface through which external enterprise "
            "agents can consume Databricks AI, data, and function services."
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


def _card_json(card: AgentCard) -> dict:
    protobuf_message = getattr(card, "_pb", card)
    return MessageToDict(
        protobuf_message,
        preserving_proto_field_name=False,
        use_integers_for_enums=False,
    )


def build_app() -> Starlette:
    # The request handler requires a card at startup. Its interface URL is not
    # returned to clients; the discovery route below creates a request-aware card.
    handler_card = _agent_card(
        os.environ.get("DATABRICKS_APP_URL", "http://localhost:8000").rstrip("/")
    )
    request_handler = DefaultRequestHandler(
        agent_executor=DatabricksMCPAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=handler_card,
    )

    async def get_agent_card(request: Request) -> JSONResponse:
        public_url = public_app_url(
            os.environ,
            request.headers,
            request.url.scheme,
        )
        return JSONResponse(_card_json(_agent_card(public_url)))

    routes = [
        Route(CARD_URL, get_agent_card, methods=["GET"]),
        *create_jsonrpc_routes(request_handler, rpc_url=RPC_URL),
    ]
    return Starlette(routes=routes)


app = build_app()


if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
