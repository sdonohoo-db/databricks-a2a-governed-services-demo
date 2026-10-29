import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable, List

import mlflow
from databricks.sdk import WorkspaceClient
from databricks_mcp import DatabricksOAuthClientProvider
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse
from pydantic import BaseModel

from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import Role
from databricks_config import (
    MCPServerConfig,
    build_mcp_server_configs,
    qualified_tool_name,
)

SYSTEM_PROMPT = (
    "You are the Databricks enterprise services agent. Use the available "
    "Databricks tools for data and function requests. Clearly distinguish "
    "tool-backed results from general model knowledge."
)
FOUNDATION_MODEL_SCOPE_PROMPT = (
    "You are a Databricks interoperability advisor. Answer only questions about "
    "A2A, MCP, Databricks AI and agent services, and enterprise agent "
    "architecture. If a request is outside this conversational scope, briefly "
    "state that it is outside the capability and do not answer it."
)
DEMO_REQUEST_KEY = "databricks_a2a_demo"
FOUNDATION_MODEL_SKILL = "databricks-foundation-model"
TOOL_SKILL_TO_SERVER = {
    "uc-tools": "functions",
    "genie": "genie",
}


def _decode_demo_request(user_input: str) -> tuple[str, str | None]:
    """Read the optional client-routing convention from an A2A text message."""
    try:
        payload = json.loads(user_input)
    except (TypeError, json.JSONDecodeError):
        return user_input, None
    if not isinstance(payload, dict):
        return user_input, None
    routing = payload.get(DEMO_REQUEST_KEY)
    task = payload.get("task")
    if not isinstance(routing, dict) or not isinstance(task, str):
        return user_input, None
    if routing.get("version") != 1:
        return user_input, None
    selected_skill_id = routing.get("selected_skill_id")
    if not isinstance(selected_skill_id, str):
        return user_input, None
    return task, selected_skill_id


def _to_chat_messages(msg: dict[str, Any]) -> List[dict]:
    msg_type = msg.get("type")
    if msg_type == "function_call":
        return [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": msg["call_id"],
                        "type": "function",
                        "function": {
                            "name": msg["name"],
                            "arguments": msg["arguments"],
                        },
                    }
                ],
            }
        ]
    elif msg_type == "message" and isinstance(msg["content"], list):
        return [
            {
                "role": "assistant" if msg["role"] == "assistant" else msg["role"],
                "content": content["text"],
            }
            for content in msg["content"]
        ]
    elif msg_type == "function_call_output":
        return [
            {
                "role": "tool",
                "content": msg["output"],
                "tool_call_id": msg["tool_call_id"],
            }
        ]
    else:
        return [
            {
                k: v
                for k, v in msg.items()
                if k in ("role", "content", "name", "tool_calls", "tool_call_id")
            }
        ]


@asynccontextmanager
async def _mcp_session(server_url: str, ws: WorkspaceClient):
    async with streamablehttp_client(
        url=server_url, auth=DatabricksOAuthClientProvider(ws)
    ) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


def _list_tools(server_url: str, ws: WorkspaceClient):
    async def inner():
        async with _mcp_session(server_url, ws) as sess:
            return await sess.list_tools()

    return asyncio.run(inner())


def _make_exec_fn(
    server_url: str, tool_name: str, ws: WorkspaceClient
) -> Callable[..., str]:
    def exec_fn(**kwargs):
        async def call_it():
            async with _mcp_session(server_url, ws) as sess:
                resp = await sess.call_tool(name=tool_name, arguments=kwargs)
                return "".join([c.text for c in resp.content])

        return asyncio.run(call_it())

    return exec_fn


class ToolInfo(BaseModel):
    server_key: str
    name: str
    spec: dict
    exec_fn: Callable


def _fetch_tool_infos(ws: WorkspaceClient, server: MCPServerConfig) -> List[ToolInfo]:
    infos: List[ToolInfo] = []
    mcp_tools = _list_tools(server.url, ws).tools
    for t in mcp_tools:
        schema = t.inputSchema.copy()
        if "properties" not in schema:
            schema["properties"] = {}
        exposed_name = qualified_tool_name(server.key, t.name)
        spec = {
            "type": "function",
            "function": {
                "name": exposed_name,
                "description": f"[{server.display_name}] {t.description or t.name}",
                "parameters": schema,
            },
        }
        infos.append(
            ToolInfo(
                server_key=server.key,
                name=exposed_name,
                spec=spec,
                exec_fn=_make_exec_fn(server.url, t.name, ws),
            )
        )
    return infos


class SingleTurnMCPAgent(ResponsesAgent):
    def _call_llm(self, history: List[dict], ws: WorkspaceClient, tool_infos):
        client = ws.serving_endpoints.get_open_ai_client()
        flat_msgs = []
        for msg in history:
            flat_msgs.extend(_to_chat_messages(msg))

        return client.chat.completions.create(
            model=os.environ["LLM_ENDPOINT_NAME"],
            messages=flat_msgs,
            **({"tools": [ti.spec for ti in tool_infos]} if tool_infos else {}),
        )

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        ws = WorkspaceClient()
        custom_inputs = request.custom_inputs or {}
        selected_skill_id = custom_inputs.get("selected_skill_id")
        if not isinstance(selected_skill_id, str):
            selected_skill_id = None

        history: List[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for inp in request.input:
            history.append(inp.model_dump())

        server_configs = build_mcp_server_configs(os.environ, ws.config.host)
        selected_server = TOOL_SKILL_TO_SERVER.get(selected_skill_id or "")
        if selected_skill_id == FOUNDATION_MODEL_SKILL:
            tool_infos = []
            history.append(
                {"role": "system", "content": FOUNDATION_MODEL_SCOPE_PROMPT}
            )
        elif selected_server:
            tool_infos = [
                tool_info
                for server in server_configs
                if server.key == selected_server
                for tool_info in _fetch_tool_infos(ws, server)
            ]
            history.append(
                {
                    "role": "system",
                    "content": (
                        "The client selected a tool-backed capability. Call an "
                        "available tool only when it can genuinely satisfy the task. "
                        "Do not answer from general model knowledge. If no tool is "
                        "suitable, do not call a tool; the host will return a "
                        "deterministic capability-mismatch response."
                    ),
                }
            )
        elif selected_skill_id:
            return self._text_response(
                f"The requested capability {selected_skill_id!r} is not available."
            )
        else:
            # Plain A2A clients retain the original autonomous tool-routing behavior.
            tool_infos = [
                tool_info
                for server in server_configs
                for tool_info in _fetch_tool_infos(ws, server)
            ]
        tools_dict = {tool_info.name: tool_info for tool_info in tool_infos}
        llm_resp = self._call_llm(history, ws, tool_infos)
        raw_choice = llm_resp.choices[0].message.to_dict()
        raw_choice["id"] = uuid.uuid4().hex
        history.append(raw_choice)

        tool_calls = raw_choice.get("tool_calls") or []
        if tool_calls:
            fc = tool_calls[0]
            name = fc["function"]["name"]
            args = json.loads(fc["function"]["arguments"])
            try:
                tool_info = tools_dict[name]
                result = tool_info.exec_fn(**args)
            except Exception as e:
                result = f"Error invoking {name}: {e}"

            history.append(
                {
                    "type": "function_call_output",
                    "role": "tool",
                    "id": uuid.uuid4().hex,
                    "tool_call_id": fc["id"],
                    "output": result,
                }
            )

            followup = (
                self._call_llm(history, ws, tool_infos=[]).choices[0].message.to_dict()
            )
            followup["id"] = uuid.uuid4().hex

            assistant_text = followup.get("content", "")
            return ResponsesAgentResponse(
                output=[
                    self.create_text_output_item(
                        text=assistant_text,
                        id=uuid.uuid4().hex,
                    )
                ],
                custom_outputs=request.custom_inputs,
            )

        if selected_server:
            return self._text_response(
                "This request cannot be answered using the selected Databricks "
                "tool-backed capability. No suitable MCP tool was invoked. Choose "
                "the Databricks interoperability advisor for questions within its "
                "conversational scope, or ask a question that matches one of the "
                "selected capability's advertised tools."
            )

        assistant_text = raw_choice.get("content", "")
        return ResponsesAgentResponse(
            output=[
                self.create_text_output_item(
                    text=assistant_text,
                    id=uuid.uuid4().hex,
                )
            ],
            custom_outputs=request.custom_inputs,
        )

    def _text_response(self, text: str) -> ResponsesAgentResponse:
        return ResponsesAgentResponse(
            output=[
                self.create_text_output_item(text=text, id=uuid.uuid4().hex)
            ]
        )


mlflow.models.set_model(SingleTurnMCPAgent())


class DatabricksMCPAgentExecutor(AgentExecutor):
    """A2A executor that delegates each user message to SingleTurnMCPAgent."""

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        task, selected_skill_id = _decode_demo_request(context.get_user_input())
        req = ResponsesAgentRequest(
            input=[{"role": "user", "content": task}],
            custom_inputs={"selected_skill_id": selected_skill_id}
            if selected_skill_id
            else None,
        )
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(None, SingleTurnMCPAgent().predict, req)

        result = ""
        for item in resp.output:
            if item.role == "assistant":
                result += item.content[0]["text"] + "\n"

        await event_queue.enqueue_event(
            new_text_message(result.strip(), role=Role.ROLE_AGENT)
        )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise RuntimeError("cancel not supported")
