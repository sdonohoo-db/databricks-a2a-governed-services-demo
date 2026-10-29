"""A2A client used by the Databricks-hosted demonstration UI."""

import asyncio
import json
import os
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx
from databricks.sdk import WorkspaceClient
from google.protobuf.json_format import MessageToDict

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest


CARD_PATH = "/.well-known/agent-card.json"
DEMO_REQUEST_KEY = "databricks_a2a_demo"


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def _card_summary(card: Any) -> dict[str, Any]:
    return {
        "name": card.name,
        "description": card.description,
        "version": card.version,
        "streaming": bool(card.capabilities.streaming),
        "skills": [
            {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "tags": list(skill.tags),
                "examples": list(skill.examples),
            }
            for skill in card.skills
        ],
        "interfaces": [
            {
                "protocol_binding": interface.protocol_binding,
                "url": interface.url,
            }
            for interface in card.supported_interfaces
        ],
    }


def _card_json(card: Any) -> dict[str, Any]:
    """Serialize the complete discovered protobuf Agent Card as JSON."""
    protobuf_message = getattr(card, "_pb", card)
    return MessageToDict(
        protobuf_message,
        preserving_proto_field_name=False,
        use_integers_for_enums=False,
    )


def _selected_skill(card: Any, selected_skill_id: str) -> dict[str, Any]:
    """Validate a Google-side routing choice against the discovered card."""
    for skill in card.skills:
        if skill.id == selected_skill_id:
            return {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
            }
    advertised_ids = ", ".join(skill.id for skill in card.skills) or "none"
    raise ValueError(
        f"Selected skill {selected_skill_id!r} is not advertised by the Agent Card. "
        f"Advertised skill IDs: {advertised_ids}."
    )


def _routed_task(prompt: str, selected_skill_id: str) -> str:
    """Encode demo routing intent inside a standards-compliant text part."""
    return json.dumps(
        {
            DEMO_REQUEST_KEY: {
                "version": 1,
                "selected_skill_id": selected_skill_id,
            },
            "task": prompt,
        }
    )


async def _provider_url(workspace: WorkspaceClient) -> str:
    explicit_url = os.environ.get("A2A_PROVIDER_URL")
    if explicit_url:
        return explicit_url.rstrip("/")

    provider_name = os.environ.get("A2A_PROVIDER_APP_NAME")
    if not provider_name:
        raise RuntimeError(
            "A2A_PROVIDER_APP_NAME is not configured. Bind the provider App "
            "resource or set A2A_PROVIDER_URL for local development."
        )
    provider = await asyncio.to_thread(
        lambda: workspace.apps.get(name=provider_name)
    )
    if not provider.url:
        raise RuntimeError(f"Provider App {provider_name!r} does not have a URL.")
    return provider.url.rstrip("/")


async def discover_agent() -> dict[str, Any]:
    """Resolve the provider App and retrieve its standard A2A Agent Card."""
    trace: list[dict[str, Any]] = []
    workspace = WorkspaceClient()

    started = perf_counter()
    provider_url = await _provider_url(workspace)
    trace.append(
        {
            "step": "Resolve provider",
            "detail": "Resolved the bound Databricks App resource to its runtime URL.",
            "duration_ms": _elapsed_ms(started),
        }
    )

    started = perf_counter()
    headers = workspace.config.authenticate()
    trace.append(
        {
            "step": "Authenticate",
            "detail": "Created an OAuth header as the client App service principal; the token stays server-side.",
            "duration_ms": _elapsed_ms(started),
        }
    )

    started = perf_counter()
    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(120),
        follow_redirects=True,
    ) as httpx_client:
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=f"{provider_url}/api",
            agent_card_path=CARD_PATH,
        )
        card = await resolver.get_agent_card()
    trace.append(
        {
            "step": "Discover capabilities",
            "detail": f"GET {provider_url}/api{CARD_PATH}",
            "duration_ms": _elapsed_ms(started),
        }
    )

    return {
        "provider_url": provider_url,
        "card": _card_summary(card),
        "card_json": _card_json(card),
        "trace": trace,
    }


async def send_message(prompt: str, selected_skill_id: str) -> dict[str, Any]:
    """Discover the provider, follow its advertised interface, and send A2A."""
    trace: list[dict[str, Any]] = []
    workspace = WorkspaceClient()

    started = perf_counter()
    provider_url = await _provider_url(workspace)
    trace.append(
        {
            "step": "Resolve provider",
            "detail": "Resolved the bound provider App without hardcoding its URL.",
            "duration_ms": _elapsed_ms(started),
        }
    )

    started = perf_counter()
    headers = workspace.config.authenticate()
    trace.append(
        {
            "step": "Authenticate",
            "detail": "Authenticated app-to-app with the client App service principal.",
            "duration_ms": _elapsed_ms(started),
        }
    )

    answer_parts: list[str] = []
    protocol_events: list[dict[str, str]] = []
    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(120),
        follow_redirects=True,
    ) as httpx_client:
        started = perf_counter()
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=f"{provider_url}/api",
            agent_card_path=CARD_PATH,
        )
        card = await resolver.get_agent_card()
        card_summary = _card_summary(card)
        trace.append(
            {
                "step": "Read Agent Card",
                "detail": f"Discovered {len(card.skills)} skills and {len(card.supported_interfaces)} interface(s).",
                "duration_ms": _elapsed_ms(started),
            }
        )

        selected_skill = _selected_skill(card, selected_skill_id)
        trace.append(
            {
                "step": "Google-side decision",
                "detail": (
                    f"Selected advertised capability {selected_skill['name']!r} "
                    f"({selected_skill['id']}) for this task. The choice is sent "
                    "as an explicit demo routing envelope inside the A2A text part; "
                    "it is not a standard A2A skill-call field."
                ),
                "duration_ms": 0,
            }
        )

        started = perf_counter()
        factory = ClientFactory(
            ClientConfig(httpx_client=httpx_client, streaming=True)
        )
        client = factory.create(card)
        interface_url = card.supported_interfaces[0].url
        trace.append(
            {
                "step": "Select interface",
                "detail": f"Selected {card.supported_interfaces[0].protocol_binding}: {interface_url}",
                "duration_ms": _elapsed_ms(started),
            }
        )

        started = perf_counter()
        message = new_text_message(
            _routed_task(prompt, selected_skill_id), role=Role.ROLE_USER
        )
        message.message_id = uuid4().hex
        request = SendMessageRequest(message=message)
        async for chunk in client.send_message(request):
            if chunk.HasField("message"):
                text = "".join(part.text for part in chunk.message.parts if part.text)
                if text:
                    answer_parts.append(text)
                    protocol_events.append({"type": "message", "detail": text})
            elif chunk.HasField("status_update"):
                protocol_events.append(
                    {
                        "type": "status_update",
                        "detail": str(chunk.status_update.status.state),
                    }
                )
            elif chunk.HasField("artifact_update"):
                protocol_events.append(
                    {"type": "artifact_update", "detail": "Artifact received"}
                )
            elif chunk.HasField("task"):
                protocol_events.append(
                    {"type": "task", "detail": str(chunk.task.id)}
                )
        trace.append(
            {
                "step": "Delegate task through A2A",
                "detail": (
                    "Sent the task and demo routing intent in a standard text message "
                    "over the card-advertised JSON-RPC interface and consumed the "
                    "streamed response."
                ),
                "duration_ms": _elapsed_ms(started),
            }
        )

    return {
        "answer": "\n".join(answer_parts).strip(),
        "provider_url": provider_url,
        "interface_url": interface_url,
        "card": card_summary,
        "card_json": _card_json(card),
        "selected_skill": selected_skill,
        "trace": trace,
        "protocol_events": protocol_events,
    }
