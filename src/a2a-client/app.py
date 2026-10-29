"""Web UI for demonstrating discovery and invocation of the A2A provider."""

import os
from pathlib import Path

import bleach
import markdown
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from a2a_gateway import discover_agent, send_message


INDEX_HTML = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
MARKDOWN_TAGS = set(bleach.sanitizer.ALLOWED_TAGS) | {
    "p",
    "pre",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "br",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}
MARKDOWN_ATTRIBUTES = {
    "a": ["href", "title"],
    "code": ["class"],
    "th": ["align"],
    "td": ["align"],
}


def render_markdown(text: str) -> str:
    """Render model Markdown and remove unsafe HTML before browser delivery."""
    rendered = markdown.markdown(
        text,
        extensions=["extra", "sane_lists"],
        output_format="html",
    )
    return bleach.clean(
        rendered,
        tags=MARKDOWN_TAGS,
        attributes=MARKDOWN_ATTRIBUTES,
        protocols={"http", "https", "mailto"},
        strip=True,
    )


async def home(_: Request) -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "a2a-demonstration-client"})


async def whoami(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "signed_in_user": request.headers.get("x-forwarded-email")
            or request.headers.get("x-forwarded-user")
            or "Databricks user",
            "a2a_call_identity": "Client App service principal",
            "provider_internal_identity": "Provider App service principal",
            "credential_boundary": (
                "OAuth is generated and used by the server; no Databricks token "
                "is sent to the browser."
            ),
        }
    )


async def discover(_: Request) -> JSONResponse:
    try:
        return JSONResponse(await discover_agent())
    except Exception as exc:
        return JSONResponse(
            {"error": type(exc).__name__, "detail": str(exc)}, status_code=502
        )


async def chat(request: Request) -> JSONResponse:
    payload = await request.json()
    prompt = str(payload.get("prompt", "")).strip()
    selected_skill_id = str(payload.get("selected_skill_id", "")).strip()
    if not prompt:
        return JSONResponse({"error": "A prompt is required."}, status_code=400)
    if not selected_skill_id:
        return JSONResponse(
            {"error": "Select a capability discovered from the Agent Card."},
            status_code=400,
        )
    if len(selected_skill_id) > 256:
        return JSONResponse(
            {"error": "The selected skill ID is invalid."}, status_code=400
        )
    if len(prompt) > 8000:
        return JSONResponse(
            {"error": "Prompt must be 8,000 characters or fewer."}, status_code=400
        )
    try:
        result = await send_message(prompt, selected_skill_id)
        result["answer_html"] = render_markdown(result["answer"])
        return JSONResponse(result)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse(
            {"error": type(exc).__name__, "detail": str(exc)}, status_code=502
        )


app = Starlette(
    routes=[
        Route("/", home),
        Route("/api/health", health),
        Route("/api/whoami", whoami),
        Route("/api/discover", discover),
        Route("/api/chat", chat, methods=["POST"]),
    ]
)


if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
