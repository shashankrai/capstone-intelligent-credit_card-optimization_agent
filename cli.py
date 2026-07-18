"""Command-line interface for the agent (with multi-turn clarification/approval + memory).

Usage:
  python cli.py "I am spending Rs 50,000 on flights. Which card should I use?"
  python cli.py --user alice          # interactive, remembers profile across turns
  python cli.py                        # interactive, anonymous
"""
from __future__ import annotations

import argparse
import uuid

from agents.graph import resume_agent, run_agent
from database.models import add_feedback


def _print_result(result: dict) -> None:
    print("\n\033[1mAgent:\033[0m")
    print(result.get("final_answer", "(no answer)"))
    print(
        f"\n\033[2m[intent={result.get('intent')} | recommended={result.get('recommended_card')} | "
        f"value=Rs {result.get('estimated_value')} | confidence={result.get('confidence')} | "
        f"guardrail={result.get('guardrail', {}).get('passed')} | latency={result.get('latency_ms')}ms | "
        f"tokens in/out={result.get('input_tokens')}/{result.get('output_tokens')}]\033[0m"
    )


def converse(query: str, user_id=None) -> None:
    print(f"\n\033[1mYou:\033[0m {query}")
    thread_id = f"cli-{uuid.uuid4().hex[:8]}"
    result = run_agent(query, user_id=user_id, thread_id=thread_id)

    # Handle human-in-the-loop pauses (clarification / approval).
    while result.get("interrupted"):
        if result.get("needs_clarification"):
            print(f"\n\033[1mAgent asks:\033[0m {result.get('clarification_question')}")
            reply = input("Your answer> ").strip()
        else:  # approval
            print(f"\n\033[1mAgent:\033[0m {result.get('approval_prompt')}")
            reply = input("Approve? (yes/no)> ").strip()
        result = resume_agent(reply, thread_id=thread_id, user_id=user_id)

    _print_result(result)

    # Optional feedback capture (Stage 3).
    qid = result.get("query_id")
    if qid and user_id:
        fb = input("\nFeedback? (u=up / d=down / enter=skip)> ").strip().lower()
        if fb in ("u", "d"):
            add_feedback(qid, user_id, "up" if fb == "u" else "down")
            print("Thanks — feedback saved.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="*", help="a one-shot query; omit for interactive mode")
    ap.add_argument("--user", default=None, help="user id for memory/personalization")
    args = ap.parse_args()

    if args.query:
        converse(" ".join(args.query), user_id=args.user)
        return

    print("Intelligent Credit Card & Rewards Agent — interactive CLI (Ctrl-C to quit)")
    if args.user:
        print(f"(memory on for user '{args.user}')")
    while True:
        try:
            q = input("\nAsk> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q:
            converse(q, user_id=args.user)


if __name__ == "__main__":
    main()
