"""Compatibility command for explicitly configured synthetic model checks."""

import argparse

from .ai_smoke_cli import run_smoke
from .providers import ProviderError, ProviderRegistry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--provider")
    parser.add_argument("--allow-model-network", action="store_true")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Explicit absolute smoke-test directory (overrides CTF_DATA_DIR).",
    )
    args = parser.parse_args()

    def build():
        try:
            registry = ProviderRegistry.from_file(args.config)
            if args.provider:
                registry.select(args.provider)
            return registry.get()
        except (KeyError, OSError, TypeError, ValueError):
            raise ProviderError("invalid_provider_configuration") from None

    run_smoke(parser, args.allow_model_network, build, data_dir=args.data_dir)


if __name__ == "__main__":
    main()
