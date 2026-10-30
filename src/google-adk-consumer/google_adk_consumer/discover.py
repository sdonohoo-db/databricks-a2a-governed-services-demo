"""Print the Databricks A2A Agent Card as a Google-side preflight."""

import asyncio
import os

import httpx
from a2a.client import A2ACardResolver

from .auth import DatabricksOAuth


async def main() -> None:
    app_url = os.environ["DATABRICKS_A2A_APP_URL"].rstrip("/")
    profile = os.environ.get("DATABRICKS_PROFILE")
    base_url = f"{app_url}/api"

    async with httpx.AsyncClient(
        auth=DatabricksOAuth(profile), timeout=60
    ) as httpx_client:
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=base_url,
            agent_card_path="/.well-known/agent-card.json",
        )
        card = await resolver.get_agent_card()

    print(f"Agent: {card.name} (version {card.version})")
    print(f"Description: {card.description}")
    print("Capabilities:")
    for skill in card.skills:
        print(f"  - {skill.name}: {skill.description}")
    print("Interfaces:")
    for interface in card.supported_interfaces:
        print(f"  - {interface.protocol_binding}: {interface.url}")


if __name__ == "__main__":
    asyncio.run(main())
