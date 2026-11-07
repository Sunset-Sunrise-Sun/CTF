"""Explicitly opted-in model smoke call; no challenge content sent or logged."""

import argparse
import asyncio
from .providers import (
    ProviderRegistry,
    ModelRequest,
    Message,
    recorded_complete,
    ProviderError,
)
from .store import Store
from .models import Challenge
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--provider")
    parser.add_argument("--allow-model-network", action="store_true")
    args = parser.parse_args()
    if not args.allow_model_network:
        parser.error("Explicit --allow-model-network required")
    registry = ProviderRegistry.from_file(args.config)
    if args.provider:
        registry.select(args.provider)
    store = Store(Path("../.local-data/model-smoke.sqlite3"))
    challenge = Challenge(name="Synthetic model connectivity test", category="Misc")
    store.create(challenge)
    try:
        asyncio.run(
            recorded_complete(
                registry.get(),
                ModelRequest(
                    messages=[
                        Message(
                            role="user",
                            content="Reply with OK. This is a synthetic connectivity test.",
                        )
                    ]
                ),
                store,
                challenge.challenge_id,
            )
        )
    except ProviderError as error:
        print("Model connectivity:", error.code)
        raise SystemExit(1) from None
    print(
        "Model connectivity: success. Only provider/model/time/status recorded locally."
    )


if __name__ == "__main__":
    main()
