"""Offline KAT reference only. No production imports, I/O to providers or keyring."""

import argparse
import datetime
import hashlib
import hmac
import json
from pathlib import Path
import re
import subprocess
import sys

SAFE = 9007199254740991
INDEX = 2147483647
DC = b"CTF/model-stream/content/v1"
DB = b"CTF/model-stream/batch/v1"
CK = set(
    "fingerprint_version key_id audit_dataset_id challenge_id request_id batch_id first_sequence last_sequence chunk_count".split()
)
EK = set(
    "provider_id model_id content_bytes_delta tool_delta_count first_received_at last_received_at".split()
)


class Rejected(Exception):
    def __init__(self, code, limit=None, structure=None):
        self.code, self.limit, self.structure = code, limit, structure


def reject(code, limit=None, structure=None):
    raise Rejected(code, limit, structure)


def guard_structure(source):
    """Iterative lexical preflight: no input object/array is constructed here.

    Count containers, not primitive values; the root container is depth 1.
    An object member is reserved at its opening key quote, before its value.
    First violation in source order wins, before semantic/duplicate-key checks.
    """
    stack = []  # At most 8 fixed-size scanner frames.
    in_string = escaped = key_string = False
    for character in source:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
                if key_string:
                    stack[-1][2] = False
            continue
        if character == '"':
            key_string = bool(stack and stack[-1][0] == "{" and stack[-1][2])
            if key_string:
                if stack[-1][1] == 16:
                    reject("limit_exceeded", "projection_structure", "object_keys")
                stack[-1][1] += 1
            in_string = True
        elif character in "{[":
            if len(stack) == 8:
                reject("limit_exceeded", "projection_structure", "container_depth")
            stack.append([character, 0, character == "{"])
        elif character in "}]":
            if not stack or stack[-1][0] != ("{" if character == "}" else "["):
                reject("invalid_json")
            stack.pop()
        elif character == "," and stack and stack[-1][0] == "{":
            stack[-1][2] = True
    # Full JSON syntax and string/token validation remain the parser's job.


def integer(v, minimum=0, maximum=SAFE):
    if type(v) is not int:
        reject("integer_type")
    if not minimum <= v <= maximum:
        reject("range_error")


def string(v, cap=262144, nonempty=False):
    if type(v) is not str:
        reject("fingerprint_schema_error")
    try:
        data = v.encode("utf-8", errors="strict")
    except UnicodeError:
        reject("invalid_json")
    if len(data) > cap:
        reject("limit_exceeded", "string_utf8_bytes")
    if nonempty and not v:
        reject("fingerprint_schema_error")
    return len(data)


def unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            reject("duplicate_key")
        string(k, 32)
        result[k] = v
    return result


def parse(raw):
    def pint(token):
        if token == "-0":
            reject("noncanonical_integer")
        if len(token.lstrip("-")) > 16:
            reject("range_error")
        value = int(token)
        if abs(value) > SAFE:
            reject("range_error")
        return value

    try:
        if raw.startswith(b"\xef\xbb\xbf"):
            reject("invalid_json")
        source = raw.decode("utf-8", errors="strict")
        guard_structure(source)
        return json.loads(
            source,
            object_pairs_hook=unique,
            parse_int=pint,
            parse_float=lambda _: reject("integer_type"),
            parse_constant=lambda _: reject("invalid_json"),
        )
    except (ValueError, UnicodeError):
        reject("invalid_json")


def canonical(v):
    # Independent stdlib serialization, after strict token/schema checks.
    def check(x):
        if isinstance(x, str):
            string(x)
        elif type(x) is int:
            integer(x)
        elif x is None:
            pass
        elif type(x) is list:
            for y in x:
                check(y)
        elif type(x) is dict:
            for k, y in x.items():
                string(k, 32)
                check(y)
        else:
            reject("fingerprint_schema_error")

    check(v)
    return json.dumps(
        v, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def keys(v, required, optional=()):
    if (
        type(v) is not dict
        or not required <= v.keys()
        or v.keys() - required - set(optional)
    ):
        reject("fingerprint_schema_error")


def timestamp(v):
    string(v)
    if not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00:00", v
    ):
        reject("timestamp_format")
    try:
        datetime.datetime.fromisoformat(v)
    except ValueError:
        reject("timestamp_format")


def field(name, v):
    name = name.split(".")[-1]
    if name in {"first_sequence", "last_sequence", "chunk_count", "chunk_sequence"}:
        integer(v, 1)
    elif name in {"choice_index", "index"}:
        integer(v, 0, INDEX)
    elif name in {"content_bytes_delta", "tool_delta_count"}:
        integer(v)
    elif name in {"first_received_at", "last_received_at"}:
        timestamp(v)
    elif name in {"audit_dataset_id", "challenge_id", "request_id", "batch_id"}:
        string(v, 36)
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", v):
            reject("fingerprint_schema_error")
    elif name == "fingerprint_version":
        if v != "stream-content-v1":
            reject("fingerprint_schema_error")
    elif name == "content_fingerprint":
        string(v, 64)
        if not re.fullmatch(r"[0-9a-f]{64}", v):
            reject("fingerprint_schema_error")
    elif name in {"key_id", "provider_id"}:
        string(v, 128, True)
    elif name == "model_id":
        string(v, 256, True)
    elif name in {"id", "name"}:
        string(v, 256)
    elif name in {"arguments", "content"}:
        if v is not None or name != "content":
            string(v)
    elif name == "type":
        if v != "function":
            reject("fingerprint_schema_error")
    else:
        reject("fingerprint_schema_error")


def frame(label, data):
    prefix = len(data).to_bytes(8, "big")
    return {
        "label": label,
        "length": len(data),
        "prefix_hex": prefix.hex(),
        "framed_hex": (prefix + data).hex(),
    }


def full(x, key):
    keys(x, {"C", "records", "M_extra"}, {"supplied_M"})
    c, records, extra = x["C"], x["records"], x["M_extra"]
    keys(c, CK)
    keys(extra, EK)
    for k, v in (c | extra).items():
        field(k, v)
    if (
        c["last_sequence"] < c["first_sequence"]
        or c["chunk_count"] != c["last_sequence"] - c["first_sequence"] + 1
    ):
        reject("context_mismatch")
    if type(records) is not list or len(records) != c["chunk_count"]:
        reject("context_mismatch")
    if len(records) > 256:
        reject("limit_exceeded", "projected_batch_bytes")
    content_bytes, deltas = 0, 0
    for seq, record in enumerate(records, c["first_sequence"]):
        keys(record, {"chunk_sequence", "choices"})
        field("chunk_sequence", record["chunk_sequence"])
        if record["chunk_sequence"] != seq:
            reject("context_mismatch")
        choices = record["choices"]
        if type(choices) is not list or not choices:
            reject("fingerprint_schema_error")
        if len(choices) > 1:
            reject("limit_exceeded", "choices_per_frame")
        for choice in choices:
            keys(choice, {"choice_index"}, {"content", "tool_deltas"})
            field("choice_index", choice["choice_index"])
            if "content" in choice:
                field("content", choice["content"])
                if choice["content"] is not None:
                    content_bytes += len(choice["content"].encode("utf-8"))
            tools = choice.get("tool_deltas", [])
            if type(tools) is not list:
                reject("fingerprint_schema_error")
            if len(tools) > 16:
                reject("limit_exceeded", "tool_deltas_per_frame")
            deltas += len(tools)
            for tool in tools:
                keys(tool, {"index"}, {"id", "type", "function"})
                for k, v in tool.items():
                    if k != "function":
                        field(k, v)
                if "function" in tool:
                    keys(tool["function"], set(), {"name", "arguments"})
                    for k, v in tool["function"].items():
                        field(k, v)
                        content_bytes += len(v.encode("utf-8"))
    if deltas > 4096:
        reject("limit_exceeded", "tool_deltas_per_request")
    if (
        content_bytes != extra["content_bytes_delta"]
        or deltas != extra["tool_delta_count"]
    ):
        reject("context_mismatch")
    if "supplied_M" in x:
        keys(x["supplied_M"], CK | EK | {"content_fingerprint"})
        for k, v in x["supplied_M"].items():
            field(k, v)
        if any(x["supplied_M"][k] != v for k, v in (c | extra).items()):
            reject("context_mismatch")
    jc = canonical(c)
    rs = [canonical(r) for r in records]
    if any(len(r) > 1048576 for r in rs):
        reject("limit_exceeded", "projected_record_bytes")
    # Size slot is only for resource checking; never MACed or persisted as a tag.
    placeholder = c | extra | {"content_fingerprint": "0" * 64}
    projected = (
        8
        + len(DC)
        + 8
        + len(jc)
        + sum(8 + len(r) for r in rs)
        + 8
        + len(DB)
        + 8
        + len(canonical(placeholder))
    )
    if projected > 2097152:
        reject("limit_exceeded", "projected_batch_bytes")
    cf = [frame("domain_content", DC), frame("J(C)", jc)] + [
        frame(f"R_{i}", r) for i, r in enumerate(rs, c["first_sequence"])
    ]
    cm = b"".join(bytes.fromhex(f["framed_hex"]) for f in cf)
    fingerprint = hmac.new(key, cm, hashlib.sha256).hexdigest()
    m = c | extra | {"content_fingerprint": fingerprint}
    jm = canonical(m)
    bf = [frame("domain_batch", DB), frame("J(M)", jm)]
    bm = b"".join(bytes.fromhex(f["framed_hex"]) for f in bf)
    return {
        "status": "ok",
        "J_C_hex": jc.hex(),
        "R_hex": [r.hex() for r in rs],
        "J_M_hex": jm.hex(),
        "M": m,
        "content_frames": cf,
        "batch_frames": bf,
        "content_message_hex": cm.hex(),
        "batch_message_hex": bm.hex(),
        "content_fingerprint": fingerprint,
        "batch_digest": hmac.new(key, bm, hashlib.sha256).hexdigest(),
        "projected_batch_bytes": projected,
    }


def evaluate(case, key):
    try:
        x = parse(bytes.fromhex(case["input_utf8_hex"]))
        if case["mode"] == "full":
            return full(x, key)
        if case["mode"] == "field":
            keys(x, {"field", "value"})
            field(x["field"], x["value"])
            return {"status": "ok", "canonical_hex": canonical(x["value"]).hex()}
        if case["mode"] == "canonical":
            return {"status": "ok", "canonical_hex": canonical(x).hex()}
        raise AssertionError("Unknown fixture mode")
    except Rejected as error:
        result = {"status": "error", "code": error.code}
        if error.limit:
            result["limit_code"] = error.limit
        if error.structure:
            result["structure_limit"] = error.structure
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--report")
    parser.add_argument("--calculate-only", action="store_true")
    parser.add_argument("--case")
    parser.add_argument("--machine", action="store_true")
    args = parser.parse_args()
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    if args.calculate_only:
        assert fixture["kind"] == "unfrozen-inputs", (
            "Cannot regenerate expected from a golden fixture"
        )
    else:
        assert fixture["kind"] == "golden", "Expected must be frozen before test"
    key = bytes.fromhex(fixture["synthetic_key_hex"])
    assert len(key) == 32
    cases = [c for c in fixture["cases"] if not args.case or c["id"] == args.case]
    assert cases
    actual = {c["id"]: evaluate(c, key) for c in cases}
    if not args.calculate_only:
        for c in cases:
            assert actual[c["id"]] == c["expected"], f"Mismatch {c['id']}"
    encoded = json.dumps(
        actual, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )
    if args.report:
        assert Path(args.report).resolve() != Path(args.fixture).resolve(), (
            "Report must not overwrite fixture"
        )
        Path(args.report).write_text(encoded + "\n", encoding="utf-8", newline="\n")
    if args.machine:
        print(encoded)
        return
    if not args.calculate_only and not args.case:
        for vector in ("V1", "V2", "V3"):
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--fixture",
                str(Path(args.fixture).resolve()),
                "--case",
                vector,
                "--machine",
            ]
            runs = [subprocess.check_output(command) for _ in range(2)]
            assert runs[0] == runs[1]
            assert json.loads(runs[0])[vector] == actual[vector]
        print(
            f"Python: {len(cases)} frozen cases PASS; 6 fresh-process V1/V2/V3 checks PASS"
        )
    else:
        print(f"Python: calculated {len(cases)} actual results (NOT a test run)")


if __name__ == "__main__":
    main()
