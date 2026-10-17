"""Chat with the agent in the terminal (no WhatsApp needed).

Commands: /reset to start over, /quit to exit.
"""

import logging
import sys

import agent
from memory import get_session, reset_session
from tools.pdf import PDF_DIR
from tools.planner import split_message

USER_ID = "cli"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # ₹ and emoji on Windows terminals
    print("TripPilot terminal chat. Type /reset to start over, /quit to exit.\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/reset":
            reset_session(USER_ID)
            print("(conversation cleared)\n")
            continue
        for chunk in split_message(agent.run(USER_ID, text)):
            print(f"\nTripPilot: {chunk}\n")
        session = get_session(USER_ID)
        for name in session.outbox_files:
            print(f"(attachment saved: {PDF_DIR / name})\n")
        session.outbox_files.clear()


if __name__ == "__main__":
    main()
