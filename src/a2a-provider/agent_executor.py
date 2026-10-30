import asyncio
import contextvars
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
from mcp.types import CallToolRequest, CallToolResult
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse
from openai import OpenAI
from opentelemetry import trace
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
MAX_TOOL_ROUNDS = 6
tracer = trace.get_tracer("databricks.a2a.provider")


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

    with tracer.start_as_current_span("unity_gateway.mcp.list_tools") as span:
        span.set_attribute("mcp.server_url", server_url)
        return asyncio.run(inner())


def _make_exec_fn(
    server: MCPServerConfig, tool_name: str, ws: WorkspaceClient
) -> Callable[..., str]:
    def exec_fn(**kwargs):
        async def call_it():
            async with _mcp_session(server.url, ws) as sess:
                params: dict[str, Any] = {
                    "name": tool_name,
                    "arguments": kwargs,
                }
                if server.call_meta:
                    params["_meta"] = dict(server.call_meta)
                request = CallToolRequest(method="tools/call", params=params)
                resp = await sess.send_request(request, CallToolResult)
                return "".join([c.text for c in resp.content])

        with tracer.start_as_current_span("unity_gateway.mcp.call_tool") as span:
            span.set_attribute("mcp.service", server.display_name)
            span.set_attribute("mcp.tool.name", tool_name)
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
                exec_fn=_make_exec_fn(server, t.name, ws),
            )
        )
    return infos


class SingleTurnMCPAgent(ResponsesAgent):
    def _call_llm(
        self,
        history: List[dict],
        ws: WorkspaceClient,
        tool_infos,
        request_tags: dict[str, str],
    ):
        auth_header = ws.config.authenticate().get("Authorization", "")
        token = auth_header.removeprefix("Bearer ")
        client = OpenAI(
            api_key=token,
            base_url=f"{ws.config.host.rstrip('/')}/ai-gateway/mlflow/v1",
        )
        flat_msgs = []
        for msg in history:
            flat_msgs.extend(_to_chat_messages(msg))

        with tracer.start_as_current_span("unity_gateway.model.invoke") as span:
            span.set_attribute("gen_ai.request.model", os.environ["MODEL_SERVICE_NAME"])
            return client.chat.completions.create(
                model=os.environ["MODEL_SERVICE_NAME"],
                messages=flat_msgs,
                extra_headers={
                    "Databricks-Ai-Gateway-Request-Tags": json.dumps(request_tags)
                },
                **({"tools": [ti.spec for ti in tool_infos]} if tool_infos else {}),
            )

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        custom_inputs = request.custom_inputs or {}
        selected_skill_id = custom_inputs.get("selected_skill_id")
        if not isinstance(selected_skill_id, str):
            selected_skill_id = None
        request_id = custom_inputs.get("a2a_request_id")
        if not isinstance(request_id, str):
            request_id = uuid.uuid4().hex
        request_tags = {
            "application": "databricks-a2a-provider",
            "a2a_request_id": request_id,
            "a2a_skill": selected_skill_id or "autonomous",
        }

        with tracer.start_as_current_span("a2a.agent.predict") as predict_span:
            predict_span.set_attribute("a2a.request.id", request_id)
            predict_span.set_attribute(
                "a2a.skill.id", selected_skill_id or "autonomous"
            )
            return self._predict(request, selected_skill_id, request_tags)

    def _predict(
        self,
        request: ResponsesAgentRequest,
        selected_skill_id: str | None,
        request_tags: dict[str, str],
    ) -> ResponsesAgentResponse:
        ws = WorkspaceClient()
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
                        f"For shipping quotes, use SQL to call the Unity Catalog "
                        f"function {os.environ.get('UC_FUNCTION_NAME', '')}. "
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
        tool_invoked = False
        raw_choice: dict[str, Any] = {}
        for _ in range(MAX_TOOL_ROUNDS):
            llm_resp = self._call_llm(
                history,
                ws,
                tool_infos,
                request_tags,
            )
            raw_choice = llm_resp.choices[0].message.to_dict()
            raw_choice["id"] = uuid.uuid4().hex
            history.append(raw_choice)

            tool_calls = raw_choice.get("tool_calls") or []
            if not tool_calls:
                break

            tool_invoked = True
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
        else:
            return self._text_response(
                "The selected capability exceeded the maximum number of tool calls."
            )

        if selected_server and not tool_invoked:
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
        request_id = uuid.uuid4().hex
        req = ResponsesAgentRequest(
            input=[{"role": "user", "content": task}],
            custom_inputs={
                "selected_skill_id": selected_skill_id,
                "a2a_request_id": request_id,
            },
        )
        with tracer.start_as_current_span("a2a.request.execute") as span:
            span.set_attribute("a2a.request.id", request_id)
            span.set_attribute("a2a.skill.id", selected_skill_id or "autonomous")
            loop = asyncio.get_running_loop()
            copied_context = contextvars.copy_context()
            resp = await loop.run_in_executor(
                None,
                copied_context.run,
                SingleTurnMCPAgent().predict,
                req,
            )

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
