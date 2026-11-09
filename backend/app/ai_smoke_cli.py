"""Run an audited fixed synthetic prompt with explicit networking consent."""

import argparse
import asyncio
import os
from pathlib import Path
import tempfile

from .ai_assistant import build_deepseek_provider, test_deepseek_connection
from .model_calls import ModelCallJournal, model_network_enabled, safe_error_code
from .providers import ProviderError


def run_smoke(parser, allow_model_network, provider_factory, data_dir=None):
    if not allow_model_network:
        parser.error("Explicit --allow-model-network required")
    if not model_network_enabled():
        parser.error("Set CTF_MODEL_NETWORK_ENABLED=true in this process environment")
    value = data_dir or os.environ.get("CTF_DATA_DIR")
    if not value or not Path(value).is_absolute():
        parser.error("CTF_DATA_DIR must be an explicit absolute smoke-test directory")
    try:
        journal = ModelCallJournal(Path(value) / "model-audit.sqlite3")
    except ProviderError:
        parser.error("Unsafe model audit path")
    root = journal.path.parent
    if any((parent / "workbench.sqlite3").exists() for parent in root.parents):
        parser.error("Use a separate smoke-test directory outside workbench data")
    if any(
        (root / name).exists()
        for name in (
            "workbench.sqlite3",
            "project.json",
            "artifacts",
            "challenges",
            "writeups",
        )
    ):
        parser.error(
            "Use a separate smoke-test directory, not a workbench data directory"
        )
    old_temp = tempfile.tempdir
    old_env = {name: os.environ.get(name) for name in ("TMPDIR", "TEMP", "TMP")}
    try:
        provider = provider_factory()
        root.mkdir(parents=True, exist_ok=True)
        smoke_tmp = tempfile.mkdtemp(prefix="model-smoke-tmp-", dir=root)
        tempfile.tempdir = smoke_tmp
        os.environ.update({name: smoke_tmp for name in old_env})
        response = asyncio.run(
            test_deepseek_connection(
                journal,
                provider,
            )
        )
    except ProviderError as error:
        print("Model connectivity:", safe_error_code(error))
        raise SystemExit(1) from None
    except Exception:
        print("Model connectivity: internal_error")
        raise SystemExit(1) from None
    finally:
        tempfile.tempdir = old_temp
        for name, previous in old_env.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
    print("Model connectivity: success. Synthetic call ID:", response.audit_call_id)


def main():
    parser = argparse.ArgumentParser(
        description="Send one fixed synthetic DeepSeek prompt."
    )
    parser.add_argument("--allow-model-network", action="store_true")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Explicit absolute smoke-test directory (overrides CTF_DATA_DIR).",
    )
    args = parser.parse_args()
    run_smoke(
        parser,
        args.allow_model_network,
        build_deepseek_provider,
        data_dir=args.data_dir,
    )


if __name__ == "__main__":
    main()
