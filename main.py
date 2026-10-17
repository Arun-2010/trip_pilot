"""FastAPI app with the Twilio WhatsApp webhook.

Replies go back inside the webhook response as TwiML. (Sending free-form WhatsApp
messages through the REST API needs an approved template on trial accounts.)

Twilio waits ~15s for the webhook, so we give the agent REPLY_WAIT_S. If live searches
take longer, we answer "still searching" and hand over the finished reply on the
customer's next message.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, Response
from twilio.twiml.messaging_response import MessagingResponse

import agent
from memory import get_session, reset_session
from tools.pdf import PDF_DIR
from tools.planner import split_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
for noisy in ("httpx", "twilio.http_client"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("trippilot.whatsapp")

app = FastAPI(title="TripPilot")

REPLY_WAIT_S = 12
STILL_WORKING = "⏳ Still fetching live prices for you. Send \"ok\" in a few seconds to see your options."
RESET_WORDS = {"reset", "/reset", "start over"}

_pool = ThreadPoolExecutor(max_workers=8)
_pending: dict[str, Future[str]] = {}  # replies that weren't ready within REPLY_WAIT_S


def _twiml(text: str, media_urls: list[str] | None = None) -> Response:
    twiml = MessagingResponse()
    messages = [twiml.message(chunk) for chunk in split_message(text)]
    for url in media_urls or []:
        messages[-1].media(url)
    return Response(content=str(twiml), media_type="application/xml")


def _public_base_url(request: Request) -> str:
    # Behind ngrok, Host is the public hostname and the original scheme is in X-Forwarded-Proto.
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{request.headers.get('host', request.url.netloc)}"


@app.get("/")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/files/{name}")
def get_file(name: str) -> FileResponse:
    # Only serve booking PDFs we generated, e.g. TP-AB6VAO.pdf (no path tricks).
    if not re.fullmatch(r"TP-[A-Z0-9]{6}\.pdf", name) or not (PDF_DIR / name).exists():
        raise HTTPException(status_code=404)
    return FileResponse(PDF_DIR / name, media_type="application/pdf", filename=name)


@app.post("/whatsapp")
def whatsapp_webhook(request: Request, From: str = Form(...), Body: str = Form("")) -> Response:
    log.info("message from %s: %s", From, Body)

    if Body.strip().lower() in RESET_WORDS:
        _pending.pop(From, None)
        reset_session(From)
        return _twiml("Starting fresh! Where would you like to go? ✈️")

    future = _pending.pop(From, None)
    if future is not None:
        log.info("delivering the reply that was still in progress (ignoring %r)", Body)
    else:
        future = _pool.submit(agent.run, From, Body)

    try:
        reply = future.result(timeout=REPLY_WAIT_S)
    except FutureTimeout:
        _pending[From] = future
        log.info("reply not ready after %ss, telling the customer to check back", REPLY_WAIT_S)
        return _twiml(STILL_WORKING)

    session = get_session(From)
    media_urls = [f"{_public_base_url(request)}/files/{name}" for name in session.outbox_files]
    session.outbox_files.clear()
    if media_urls:
        log.info("attaching %s", media_urls)
    return _twiml(reply, media_urls)
