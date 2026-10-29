import asyncio
import logging
import os
from uuid import uuid4

import httpx
from databricks.sdk.core import Config

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest


# Where the local A2A server is reachable. Override with A2A_BASE_URL when running
# against a deployed Databricks App.
BASE_URL = os.environ.get("A2A_BASE_URL", "http://localhost:8000/api")
CARD_PATH = "/.well-known/agent-card.json"
PROFILE = os.environ.get("DATABRICKS_PROFILE")
USER_PROMPT = os.environ.get(
    "PROMPT",
    "Give me a governed shipping quote from Boston to Chicago for 25 kilograms.",
)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Local runs hit localhost without auth; remote runs need a Databricks OAuth token.
    headers: dict[str, str] = {}
    if not BASE_URL.startswith("http://localhost"):
        if not PROFILE:
            raise RuntimeError(
                "Set DATABRICKS_PROFILE explicitly when querying a deployed app."
            )
        token = Config(profile=PROFILE).oauth_token().access_token
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=100, headers=headers) as httpx_client:
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=BASE_URL,
            agent_card_path=CARD_PATH,
        )
        agent_card = await resolver.get_agent_card()
        print(agent_card)

        factory = ClientFactory(
            ClientConfig(httpx_client=httpx_client, streaming=True)
        )
        client = factory.create(agent_card)
        logger.info("A2A Client initialized.")

        message = new_text_message(USER_PROMPT, role=Role.ROLE_USER)
        message.message_id = uuid4().hex
        request = SendMessageRequest(message=message)

        async for chunk in client.send_message(request):
            if chunk.HasField("message"):
                for part in chunk.message.parts:
                    if part.text:
                        print(f"agent: {part.text}")
            elif chunk.HasField("status_update"):
                print(f"status: {chunk.status_update.status.state}")
            elif chunk.HasField("artifact_update"):
                print(f"artifact: {chunk.artifact_update.artifact}")
            elif chunk.HasField("task"):
                print(f"task: {chunk.task.id} ({chunk.task.status.state})")


if __name__ == "__main__":
    asyncio.run(main())
