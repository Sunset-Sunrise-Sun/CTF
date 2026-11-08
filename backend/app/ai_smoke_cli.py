"""Explicit synthetic DeepSeek connectivity smoke test.

No challenge description, attachment, or user content is sent. The call is
recorded in a separate local SQLite database under CTF_DATA_DIR.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .ai_assistant import build_deepseek_provider, model_network_enabled
from .models import Challenge
from .providers import Message, ModelRequest, ProviderError, recorded_complete
from .store import Store


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a synthetic OK prompt to the configured DeepSeek endpoint."
    )
    parser.add_argument(
        "--allow-model-network",
        action="store_true",
        help="Explicitly permit this synthetic network request.",
    )
    args = parser.parse_args()
    if not args.allow_model_network:
        parser.error("Explicit --allow-model-network required")
    if not model_network_enabled():
        parser.error("Set CTF_MODEL_NETWORK_ENABLED=true in this process environment")
    configured_root = os.environ.get("CTF_DATA_DIR")
    if not configured_root:
        parser.error("Set CTF_DATA_DIR to a dedicated local data directory before running the smoke test")
    data_root = Path(configured_root)
    if not data_root.is_absolute():
        parser.error("CTF_DATA_DIR must be an absolute path; refusing an ambiguous relative data location")
    store = Store(data_root / "model-smoke.sqlite3")
    challenge = Challenge(
        name="Synthetic model connectivity test",
        category="Misc",
        ai_usage_level="A2",
    )
    store.create(challenge)
    try:
        response = asyncio.run(
            recorded_complete(
                build_deepseek_provider(),
                ModelRequest(
                    messages=[
                        Message(
                            role="user",
                            content="Reply with OK. This is a synthetic connectivity test; no user-provided content is included.",
                        )
                    ]
                ),
                store,
                challenge.challenge_id,
            )
        )
    except ProviderError as error:
        print("DeepSeek connectivity:", error.code)
        raise SystemExit(1) from None
    print(
        "DeepSeek connectivity: success. "
        f"Provider={response.provider_id}; model={response.model_id}. "
        "Only synthetic content was sent; response text was not printed."
    )


if __name__ == "__main__":
    main()
