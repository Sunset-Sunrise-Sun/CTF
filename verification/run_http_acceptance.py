"""Real-HTTP acceptance for the unified P0 candidate.

Starts uvicorn in a subprocess with an isolated data directory, drives the API
with an external httpx client, and writes a full request/response transcript.
It does not import application code and never sends real challenge data, real
API keys, or network model requests.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PORT = int(os.environ.get("P0_HTTP_PORT", "18080"))
BASE = f"http://127.0.0.1:{PORT}"
DATA = Path(tempfile.mkdtemp(prefix="p0-http-acceptance-")) / "data"
TRANSCRIPT: list[dict] = []
CHECKS: list[dict] = []


def record(name: str, ok: bool, detail: str) -> None:
    ok = bool(ok)
    CHECKS.append({"name": name, "ok": ok, "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " :: " + detail)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def call(method: str, path: str, **kwargs) -> httpx.Response:
    response = client.request(method, BASE + path, **kwargs)
    body = response.content
    TRANSCRIPT.append(
        {
            "method": method,
            "path": path,
            "request": kwargs.get("json"),
            "status": response.status_code,
            "response": (
                response.json()
                if "json" in response.headers.get("content-type", "")
                else {"bytes": len(body), "sha256": sha(body)}
            ),
        }
    )
    return response


def wait_for_server(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                response = httpx.get(BASE + "/api/health", timeout=2)
                if response.status_code == 200:
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError("uvicorn did not become healthy")


def main() -> int:
    global client
    DATA.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "CTF_DATA_DIR": str(DATA),
            "CTF_MODEL_NETWORK_ENABLED": "false",
            "CTF_RUN_LIVE_MODEL": "0",
            "PYTHONPATH": str(BACKEND),
            "PYTHONUNBUFFERED": "1",
        }
    )
    server_out = open(DATA.parent / "server.stdout.log", "w", encoding="utf-8")
    server_err = open(DATA.parent / "server.stderr.log", "w", encoding="utf-8")
    server = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--log-level",
            "warning",
        ],
        cwd=BACKEND,
        env=env,
        stdout=server_out,
        stderr=server_err,
        text=True,
    )
    try:
        wait_for_server()
        with httpx.Client(timeout=30) as c:
            client = c
            health = call("GET", "/api/health")
            record(
                "health",
                health.status_code == 200
                and health.json()["read_only_tool_execution_enabled"] is True
                and health.json()["execution_enabled"] is False
                and health.json()["model_network_enabled"] is False,
                health.text,
            )

            challenge = call(
                "POST",
                "/api/challenges",
                json={
                    "name": "HTTP synthetic tool closure",
                    "category": "Misc",
                    "ai_usage_level": "A2",
                },
            )
            assert challenge.status_code == 201, challenge.text
            cid = challenge.json()["challenge_id"]
            workspace = DATA / "challenges" / cid
            workspace.mkdir(parents=True, exist_ok=True)
            sample = (
                bytes.fromhex("7f454c46")
                + b"\x02\x01"
                + b"\x00" * 14
                + b"\x3e\x00"
                + b" HTTP_ACCEPTANCE_TOOL_MARKER "
            )
            (workspace / "sample.bin").write_bytes(sample)

            catalog = call("GET", "/api/tools")
            names = {item["name"] for item in catalog.json()["tools"]}
            record(
                "fixed-tool-catalog",
                catalog.status_code == 200 and len(names) == 7 and "file_inspect" in names,
                ",".join(sorted(names)),
            )

            traversal = call(
                "POST",
                f"/api/challenges/{cid}/tool-proposals",
                json={
                    "tool_name": "file_inspect",
                    "arguments": {"path": "../outside.txt"},
                    "reason": "must be rejected",
                },
            )
            record(
                "path-traversal-rejected",
                traversal.status_code == 422,
                traversal.text,
            )

            proposal = call(
                "POST",
                f"/api/challenges/{cid}/tool-proposals",
                json={
                    "tool_name": "file_inspect",
                    "arguments": {"path": "sample.bin"},
                    "reason": "HTTP acceptance synthetic file check",
                },
            )
            proposal_json = proposal.json()
            pid = proposal_json["proposal_id"]
            record(
                "proposal-pending",
                proposal.status_code == 201
                and proposal_json["status"] == "pending"
                and proposal_json["model_call_id"] is None,
                pid,
            )

            before = call("GET", f"/api/challenges/{cid}/events").json()
            record(
                "no-execution-before-approval",
                [event["event_type"] for event in before]
                == ["tool_proposed"],
                ",".join(event["event_type"] for event in before),
            )

            approved = call(
                "POST",
                f"/api/challenges/{cid}/tool-proposals/{pid}/approve",
                json={"approving_user": "http-acceptance", "note": "synthetic approval"},
            )
            approved_json = approved.json()
            record(
                "approve-does-not-execute",
                approved.status_code == 200
                and approved_json["status"] == "approved"
                and approved_json["execution_id"] is None
                and bool(approved_json["approval_id"]),
                approved_json["status"],
            )
            after_approve = call("GET", f"/api/challenges/{cid}/events").json()
            record(
                "approve-event-order",
                [event["event_type"] for event in after_approve]
                == ["tool_proposed", "tool_approved"],
                ",".join(event["event_type"] for event in after_approve),
            )

            duplicate_approve = call(
                "POST",
                f"/api/challenges/{cid}/tool-proposals/{pid}/approve",
                json={"approving_user": "http-acceptance"},
            )
            record(
                "duplicate-approve-409",
                duplicate_approve.status_code == 409,
                duplicate_approve.text,
            )

            executed = call(
                "POST", f"/api/challenges/{cid}/tool-proposals/{pid}/execute"
            )
            executed_json = executed.json()
            record(
                "execute-succeeds-with-artifact",
                executed.status_code == 200
                and executed_json["status"] == "succeeded"
                and executed_json["execution_id"]
                and bool(executed_json["output_artifact_id"])
                and bool(executed_json["output_sha256"]),
                executed.text[:1000],
            )

            duplicate_execute = call(
                "POST", f"/api/challenges/{cid}/tool-proposals/{pid}/execute"
            )
            record(
                "duplicate-execute-409",
                duplicate_execute.status_code == 409,
                duplicate_execute.text,
            )

            artifact = call(
                "GET",
                f"/api/challenges/{cid}/artifacts/{executed_json['output_artifact_id']}/content",
            )
            record(
                "artifact-integrity",
                artifact.status_code == 200
                and sha(artifact.content) == executed_json["output_sha256"],
                sha(artifact.content),
            )

            events = call("GET", f"/api/challenges/{cid}/events").json()
            record(
                "event-chain-order",
                [event["event_type"] for event in events]
                == [
                    "tool_proposed",
                    "tool_approved",
                    "tool_started",
                    "artifact_added",
                    "tool_finished",
                ],
                ",".join(event["event_type"] for event in events),
            )
            finished = next(e for e in events if e["event_type"] == "tool_finished")
            record(
                "traceability-chain",
                finished["payload"]["proposal_id"] == pid
                and finished["payload"]["execution_id"] == executed_json["execution_id"]
                and finished["payload"]["artifact_ids"]
                == [executed_json["output_artifact_id"]],
                json.dumps(finished["payload"], ensure_ascii=False)[:1000],
            )

            # A downgrade after proposal must block approval/execution.
            downgraded = call(
                "POST",
                "/api/challenges",
                json={
                    "name": "HTTP synthetic A1",
                    "category": "Misc",
                    "ai_usage_level": "A1",
                },
            ).json()["challenge_id"]
            denied = call(
                "POST",
                f"/api/challenges/{downgraded}/tool-proposals",
                json={
                    "tool_name": "file_inspect",
                    "arguments": {"path": "sample.bin"},
                    "reason": "A1 must be denied",
                },
            )
            record("a1-tool-denied", denied.status_code == 403, denied.text)

            flag = call(
                "POST",
                f"/api/challenges/{cid}/flag-confirmation",
                json={
                    "flag": "flag{SYNTHETIC_HTTP_ACCEPTANCE_ONLY}",
                    "confirmed_by": "http-acceptance",
                    "note": "synthetic",
                },
            )
            record(
                "flag-hash-only",
                flag.status_code == 201
                and flag.json()["payload"]["platform_verified"] is False
                and "flag{SYNTHETIC_HTTP_ACCEPTANCE_ONLY}"
                not in json.dumps(flag.json(), ensure_ascii=False),
                flag.text[:1000],
            )

            preview = call("GET", f"/api/challenges/{cid}/writeup/preview").json()
            record(
                "writeup-tool-disclosure",
                preview["tool_proposal_count"] == 1
                and preview["tool_execution_count"] == 1
                and "工具" in preview["markdown"],
                "counts="
                + json.dumps(
                    {
                        "proposals": preview["tool_proposal_count"],
                        "executions": preview["tool_execution_count"],
                    }
                ),
            )

            export = call("GET", f"/api/challenges/{cid}/export")
            members: dict[str, bytes] = {}
            if export.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
                    members = {name: archive.read(name) for name in archive.namelist()}
            manifest = json.loads(members.get("manifest.json", b"{}"))
            disclosure = members.get("ai_disclosure.md", b"").decode("utf-8")
            record(
                "zip-manifest-disclosure-snapshot",
                export.status_code == 200
                and manifest["counts"]["tool_proposals"] == 1
                and manifest["counts"]["tool_executions"] == 1
                and manifest["read_only_tool_execution_enabled"] is True
                and "工具" in disclosure
                and "人工确认 Flag" in disclosure
                and "synthetic-credential" not in disclosure,
                "zip_sha256=" + sha(export.content),
            )
            if "SHA256SUMS" in members:
                listed = {}
                for line in members["SHA256SUMS"].decode("utf-8").splitlines():
                    digest, name = line.split("  ", 1)
                    listed[name] = digest
                actual = {
                    name: sha(data)
                    for name, data in members.items()
                    if name != "SHA256SUMS"
                }
                record(
                    "sha256sums-covers-delivered-files",
                    listed == actual,
                    f"{len(listed)} entries",
                )

            record(
                "transcript",
                True,
                f"{len(TRANSCRIPT)} HTTP requests recorded",
            )
        return 0 if all(item["ok"] for item in CHECKS) else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        server_out.close()
        server_err.close()
        (DATA.parent / "transcript.json").write_text(
            json.dumps(TRANSCRIPT, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (DATA.parent / "results.json").write_text(
            json.dumps(
                {
                    "checks": CHECKS,
                    "passed": sum(item["ok"] for item in CHECKS),
                    "failed": sum(not item["ok"] for item in CHECKS),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Evidence root: {DATA.parent}")
        print(
            "Result:",
            sum(item["ok"] for item in CHECKS),
            "passed,",
            sum(not item["ok"] for item in CHECKS),
            "failed",
        )


if __name__ == "__main__":
    raise SystemExit(main())
