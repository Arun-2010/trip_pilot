# TripPilot

A WhatsApp travel agent that turns a messy trip request ("need goa trip for 4 ppl next month,
budget 60k, hotel near beach") into live-priced flight + hotel quotes, a final itinerary, and
(bonus) a test-mode flight booking.

## How it works

```
WhatsApp → Twilio → ngrok → POST /whatsapp (main.py)
                                   │
                              agent.run()  ←── cli.py uses the same function
                                   │
                    Gemini (llm.py) ⇄ tools (function calling, max 6 rounds)
                                   │
       search_flights / search_hotels (SerpAPI) → build_quote / build_itinerary (planner.py)
                                   │
                              book_flight (demo booking; Duffel test mode optional)
```

- **No agent framework**: the loop in `agent.py` is ~40 lines of plain Python.
- **The LLM never does maths**: search results are stored on the user's session and
  `tools/planner.py` computes every rupee.
- **Results are trimmed** before Gemini sees them, which saves tokens.
- **SerpAPI responses are cached** in `cache/` while `USE_CACHE=true`.
- Replies go back as TwiML inside the webhook response (trial accounts can't send free-form
  WhatsApp messages via the REST API). Flight and hotel searches run in parallel to stay under
  Twilio's ~15s webhook limit; if they're slower, the bot says "still fetching" and delivers the
  result on the next message.
- After a booking, a **PDF confirmation** (`tools/pdf.py`) is attached to the WhatsApp reply.

## Setup

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # then fill in the keys
```

| Key | Where to get it |
|---|---|
| `GEMINI_API_KEY`, `GEMINI_MODEL` | aistudio.google.com (use the newest stable Flash model name) |
| `SERPAPI_KEY` | serpapi.com dashboard |
| `TWILIO_*` | Twilio console → Messaging → Try WhatsApp |
| `DUFFEL_API_KEY` | Optional. Only with `BOOKING_PROVIDER=duffel`; **test mode** key (`duffel_test_...`) |

## Run

```bash
pytest                                   # offline tests, no keys needed
python cli.py                            # chat in the terminal
uvicorn main:app --reload --port 8000    # WhatsApp server
ngrok http 8000                          # set https://<ngrok>/whatsapp as the sandbox webhook
```

Send `reset` (WhatsApp) or `/reset` (CLI) to start a new conversation.

## Notes

- Flights are searched with `adults=1` so the price is clearly per person; the planner multiplies by group size.
- Goa is searched as `GOI,GOX` in one request, covering both airports.
- Google Flights only shows return legs after you pick an outbound, so the itinerary makes one
  extra search (`departure_token`) for the chosen option.
- Booking is a **demo booking** by default (`BOOKING_PROVIDER=simulated`): it returns a reference
  like `TP-7K3QX9` with no real ticket or payment. Real flight-booking APIs need business
  accreditation (Duffel doesn't accept India-registered accounts, and Amadeus closed its
  self-service portal in July 2026). A Duffel test-mode integration is already in
  `tools/booking.py`; set `BOOKING_PROVIDER=duffel` and a `duffel_test_...` key to use it.
