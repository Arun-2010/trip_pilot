# TripPilot: WhatsApp travel quote agent

## What this project is

A WhatsApp agent for travel agencies. A customer sends a trip request in plain, messy language
(e.g. "need goa trip for 4 ppl next month, budget 60k, hotel near beach"). The agent:

1. Understands the request and pulls out the trip details
2. Asks follow-up questions for anything missing (origin city, exact dates, nights)
3. Fetches **live** flight and hotel prices from Google Flights and Google Hotels (via SerpAPI)
4. Builds 2–3 options that fit the budget and sends them as a quote
5. Sends a **final booking itinerary** once the customer picks an option
6. (Bonus) Books the flight in **test mode** (no real payment)

This is a demo project for the AI Engineering Intern role at Flyo. The reviewer asked for:
real prices from real websites (hotels + flights), a final booking itinerary, and booking via
the agent as a bonus. Every decision should serve a clear, working demo video.

## Tech stack

| Part | Tool |
|---|---|
| Language | Python 3.11+ |
| Web server | FastAPI + uvicorn |
| WhatsApp | Twilio WhatsApp sandbox |
| Local tunnel | ngrok (exposes localhost to Twilio) |
| LLM | Google Gemini, newest stable Flash model, via the `google-genai` SDK |
| Live prices | SerpAPI: `google_flights` and `google_hotels` engines |
| Data validation | Pydantic v2 |
| Conversation memory | In-memory dict keyed by WhatsApp number (SQLite later only if needed) |
| Config | python-dotenv, keys in `.env` |
| Bonus booking | Duffel API in test mode |

No LangChain, CrewAI or other agent frameworks. The agent loop is written by hand using
Gemini's native function calling, so every step is easy to read, debug and explain.

## Folder structure

```
trip-agent/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── .env.example          # key names only, no values
├── .gitignore            # must include .env and cache/
├── main.py               # FastAPI app + /whatsapp webhook
├── cli.py                # chat with the agent in the terminal (no WhatsApp)
├── agent.py              # agent loop: history + LLM + tool calls
├── llm.py                # the ONLY file that talks to Gemini (easy to swap providers)
├── prompts.py            # system prompt
├── models.py             # Pydantic models (TripRequest, FlightOption, HotelOption, Quote)
├── memory.py             # per-user conversation store
├── tools/
│   ├── flights.py        # search_flights via SerpAPI google_flights
│   ├── hotels.py         # search_hotels via SerpAPI google_hotels
│   ├── planner.py        # budget check, option building, itinerary formatting
│   └── booking.py        # bonus: Duffel test-mode booking
├── cache/                # saved SerpAPI responses (gitignored)
└── tests/
```

## Environment variables (.env)

```
GEMINI_API_KEY=
GEMINI_MODEL=            # newest stable Flash model name from AI Studio
SERPAPI_KEY=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
USE_CACHE=true           # true while developing, false for final demo
DUFFEL_API_KEY=          # bonus only, test-mode key
```

Never hardcode keys. Never commit `.env`. Read the model name from `GEMINI_MODEL`, never hardcode it.

## How a message flows

1. Customer sends a WhatsApp message.
2. Twilio forwards it to `POST /whatsapp` (through ngrok).
3. `main.py` loads that user's history from `memory.py` and calls `agent.run(user_id, text)`.
4. `agent.py` sends history + system prompt + tool definitions to Gemini via `llm.py`.
5. If Gemini returns a function call, run the matching tool, append the result, call Gemini again.
   Loop until Gemini returns plain text. Cap at 6 tool rounds per message to avoid runaway loops.
6. Save history, reply to Twilio.

The same `agent.run()` is used by both `main.py` (WhatsApp) and `cli.py` (terminal).

## Trip details (TripRequest)

Required before searching:
- `origin` city (convert to airport code)
- `destination` city (convert to airport code)
- `depart_date`, `return_date` (YYYY-MM-DD, must be in the future)
- `adults` (number of travellers)
- `budget_inr` (total for the whole group)

Optional: `hotel_preference` (e.g. "near beach"), `children`, `rooms` (default ceil(adults / 2)).

Rules:
- Resolve relative dates ("next month", "this weekend") against today's date, then confirm with the customer.
- If anything required is missing, ask for it in ONE short message, not one question at a time.
- Goa has two airports: GOI (Dabolim) and GOX (Mopa). Search both and pick the better result.

## Tools the LLM can call

| Tool | Input | Output |
|---|---|---|
| `search_flights` | origin, destination, depart_date, return_date, adults | top 5 round-trip options, trimmed |
| `search_hotels` | location query, check_in, check_out, adults, preference | top 5 hotels, trimmed |
| `build_quote` | flights, hotels, adults, nights, rooms, budget_inr | 2–3 options with full cost breakdown |
| `build_itinerary` | chosen option | final itinerary text |
| `book_flight` (bonus) | chosen flight + passenger names | test-mode booking reference |

### SerpAPI notes
- Flights: engine `google_flights`, params `departure_id`, `arrival_id`, `outbound_date`,
  `return_date`, `adults`, `currency=INR`, `gl=in`, `hl=en`.
- Hotels: engine `google_hotels`, params `q`, `check_in_date`, `check_out_date`, `adults`,
  `currency=INR`, `gl=in`, `hl=en`.
- Check the SerpAPI docs before relying on any field name.
- **Trim results before giving them to the LLM**: keep only airline, flight number, times,
  duration, stops, price (flights) and name, rating, price per night, location, link (hotels).
  Raw SerpAPI JSON is huge and wastes tokens.

### Caching (important: free SerpAPI searches are limited)
- When `USE_CACHE=true`, save every SerpAPI response to `cache/<hash of params>.json`
  and reuse it on the next identical call.
- Only use live searches for final testing and the demo recording.

## Budget logic

- Flight cost = round-trip price per person × adults
- Hotel cost = price per night × nights × rooms
- Total = flight cost + hotel cost
- Build up to 3 options: **Cheapest**, **Best value** (good rating for the price), **Comfort**
  (best option still within budget).
- If nothing fits, say so honestly, show the closest option and how much it is over budget.
- Do all money maths in Python (`planner.py`), never let the LLM do arithmetic.

## Reply style (WhatsApp)

- Short, friendly, plain text. Use simple line breaks and a few bullets, no markdown tables.
- Prices in ₹ with commas (₹58,400).
- Keep each message under about 1,500 characters; split long itineraries into two messages.
- Always state that prices are live and may change at booking time.

## Final itinerary must include

Traveller count, dates, outbound and return flights (airline, flight number, times),
hotel (name, area, check-in/out, rooms), cost breakdown, grand total, and a booking link or
test-mode booking reference.

## Build order (do one phase at a time, test before moving on)

- [ ] Phase 1: Setup: venv, requirements, `.env.example`, `.gitignore`, folder structure
- [ ] Phase 2: Brain in terminal: `llm.py`, `prompts.py`, `models.py`, `agent.py`, `cli.py`.
      Extract details and ask for missing ones. No tools yet.
- [ ] Phase 3: Live prices: `tools/flights.py`, `tools/hotels.py` with caching and trimming
- [ ] Phase 4: Quote + itinerary: `tools/planner.py`, full conversation works in `cli.py`
- [ ] Phase 5: WhatsApp: `main.py`, `memory.py`, Twilio sandbox + ngrok
- [ ] Phase 6 (bonus): `tools/booking.py` with Duffel test mode
- [ ] Phase 7: README, clean-up, record demo

## Commands

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python cli.py                                       # test in terminal
uvicorn main:app --reload --port 8000               # start server
ngrok http 8000                                     # public URL for Twilio webhook
```

## Coding rules

- Type hints everywhere; small functions; clear names.
- Every external call (Gemini, SerpAPI, Twilio, Duffel) has a timeout and a friendly error
  message for the customer if it fails ("Sorry, I couldn't fetch prices right now, trying again…").
- Log each tool call and its timing to the console, since this is useful in the demo video.
- Don't add new dependencies without saying why.
- Don't build ahead of the current phase.
- Keep it simple: this is a 2–3 day demo, not a production system.

## Demo script (for the video)

1. Send: "need goa trip for 4 ppl next month, budget 60k, hotel near beach"
2. Agent asks for origin city and dates; reply "from hyderabad, 14 to 17 nov"
3. Agent sends 2–3 options with live prices (show Google Flights side by side to prove it's live)
4. Reply "A"; agent sends the final itinerary
5. (Bonus) "book it"; agent returns a test-mode booking reference