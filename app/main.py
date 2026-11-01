"""FastAPI service: /chat answers from the knowledge base, /handover passes
the visitor to a person. Also serves the widget and a demo page."""
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import guardrails
from .config import ROOT, Settings
from .kb import KnowledgeBase
from .notifiers import make_notifier
from .store import Store

log = logging.getLogger("support_chatbot")

DONT_KNOW = ("I don't have that in our help docs, so I'd rather not guess. "
             "I can pass your question to the team and they'll reply by email.")
HUMAN_OK = "Of course. Leave your name and email and a person from the team will get back to you."
UNAVAILABLE = ("Sorry, the assistant isn't available right now. Leave your name and email "
               "and the team will answer your question directly.")


class Turn(BaseModel):
    role: str = Field(..., pattern="^(visitor|assistant)$")
    text: str = Field(..., max_length=4000)


class ChatIn(BaseModel):
    message: str
    history: List[Turn] = Field(default_factory=list, max_length=40)


class HandoverIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=254)
    question: str = Field(..., min_length=1, max_length=2000)
    reason: str = Field("visitor_request", max_length=60)
    transcript: List[Turn] = Field(default_factory=list, max_length=40)


def render_demo_page(note: str, widget_tag: str, extra_css: str = "") -> str:
    template = (ROOT / "demo" / "site.template.html").read_text(encoding="utf-8")
    return (template.replace("{{NOTE}}", note).replace("{{WIDGET_TAG}}", widget_tag)
            .replace("{{EXTRA_CSS}}", extra_css))


def create_app(settings: Optional[Settings] = None, answerer=None, notifier=None, store=None,
               clock=None) -> FastAPI:
    settings = settings or Settings.from_env()
    kb = KnowledgeBase.from_dir(settings.knowledge_base_dir)
    store = store or Store(settings.database_path)
    notifier = notifier or make_notifier(settings)
    if answerer is None:
        from .llm import ClaudeAnswerer

        answerer = ClaudeAnswerer(settings.company_name, settings.top_k, settings.llm_model, settings.llm_max_tokens)
    limiter_kwargs = {"clock": clock} if clock else {}
    chat_limiter = guardrails.RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_per_day, **limiter_kwargs)
    handover_limiter = guardrails.RateLimiter(3, 20, **limiter_kwargs)

    app = FastAPI(title=f"{settings.company_name} support chatbot", docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.state.settings, app.state.store, app.state.kb = settings, store, kb

    def client_ip(request: Request) -> str:
        if settings.trust_proxy_headers:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def too_many(wait: float) -> JSONResponse:
        return JSONResponse(
            {"detail": "You're sending messages too quickly. Please wait a moment and try again."},
            status_code=429, headers={"Retry-After": str(int(wait) + 1)},
        )

    def reply(text: str, status: str, citations=None, offer_handover=False, reason=None) -> dict:
        return {"reply": text, "status": status, "citations": citations or [],
                "offer_handover": offer_handover, "handover_reason": reason}

    @app.get("/health")
    def health():
        return {"ok": True, "documents": kb.sources, "sections": len(kb.chunks)}

    @app.get("/", response_class=HTMLResponse)
    def demo_page():
        return render_demo_page(
            note="Fictional company for a demo. The chat bubble in the corner is the live widget, talking to this server.",
            widget_tag=f'<script src="/widget.js" data-api="" data-company="{settings.company_name}" '
                       f'data-max-chars="{settings.max_message_chars}" defer></script>',
        )

    @app.get("/widget.js")
    def widget():
        return FileResponse(ROOT / "widget" / "widget.js", media_type="application/javascript")

    @app.post("/chat")
    def chat(body: ChatIn, request: Request):
        wait = chat_limiter.check(client_ip(request))
        if wait:
            return too_many(wait)

        message = guardrails.clean_text(body.message)
        if not message:
            return JSONResponse({"detail": "Please type a question."}, status_code=422)
        if len(message) > settings.max_message_chars:
            return JSONResponse(
                {"detail": f"Please keep messages under {settings.max_message_chars} characters."},
                status_code=422,
            )

        if guardrails.wants_human(message):
            return reply(HUMAN_OK, "handover", offer_handover=True, reason="visitor_request")

        hits = kb.search(message, settings.top_k)
        if not hits:
            # Nothing in the docs even shares a keyword: don't spend a model call on it.
            return reply(DONT_KNOW, "not_in_knowledge_base", offer_handover=True, reason="not_in_knowledge_base")

        if store.month_spend() >= settings.monthly_spend_cap_usd:
            log.warning("Monthly spend cap reached; chat is answering with the handover offer only.")
            return reply(UNAVAILABLE, "unavailable", offer_handover=True, reason="spend_cap")

        history = [{"role": t.role, "text": guardrails.clean_text(t.text)[: settings.max_message_chars * 4]}
                   for t in body.history[-settings.max_history_turns:]]
        try:
            result = answerer.answer(message, history, hits)
        except Exception:
            log.exception("Model call failed")
            return reply(UNAVAILABLE, "unavailable", offer_handover=True, reason="model_error")

        cost = guardrails.estimate_cost(result.input_tokens, result.output_tokens,
                                        settings.price_input_per_mtok, settings.price_output_per_mtok)
        store.record_usage(result.input_tokens, result.output_tokens, cost)

        # Only keep citations that point at a section we actually gave the model.
        citations = []
        for i in dict.fromkeys(result.citations):
            if isinstance(i, int) and 1 <= i <= len(hits):
                c = {"source": hits[i - 1].chunk.source, "heading": hits[i - 1].chunk.heading}
                if c not in citations:
                    citations.append(c)

        if result.status == "answered" and citations:
            return reply(result.answer, "answered", citations)
        if result.status == "needs_human":
            return reply(result.answer or HUMAN_OK, "needs_human", offer_handover=True, reason="needs_human")
        # "not_in_knowledge_base", or an "answered" with no checkable source: treat as not confident.
        text = result.answer if result.status == "not_in_knowledge_base" and result.answer else DONT_KNOW
        return reply(text, "not_in_knowledge_base", offer_handover=True, reason="not_in_knowledge_base")

    @app.post("/handover")
    def handover(body: HandoverIn, request: Request):
        wait = handover_limiter.check(client_ip(request))
        if wait:
            return too_many(wait)
        name = guardrails.clean_text(body.name)
        email = body.email.strip()
        question = guardrails.clean_text(body.question)
        if not name or not question:
            return JSONResponse({"detail": "Please fill in your name and question."}, status_code=422)
        if not guardrails.valid_email(email):
            return JSONResponse({"detail": "That email address doesn't look right."}, status_code=422)

        transcript = [{"role": t.role, "text": t.text[:2000]} for t in body.transcript[-20:]]
        lead_id = store.add_lead(name, email, question, body.reason, transcript)
        try:
            notifier.notify(store.get_lead(lead_id))
            store.mark_notified(lead_id)
        except Exception as exc:  # the lead is already saved; log and carry on
            log.exception("Handover notification failed for lead %s", lead_id)
            store.mark_notified(lead_id, error=f"{type(exc).__name__}: {exc}"[:500])
        return {"ok": True, "lead_id": lead_id,
                "message": f"Thanks {name}. The team has your question and will reply to {email}."}

    return app


def _lazy_app():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run("app.main:_lazy_app", factory=True, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))
