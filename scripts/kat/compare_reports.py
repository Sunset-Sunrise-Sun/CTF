"""Compare independently computed actual reports to the read-only golden fixture."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", required=True)
    p.add_argument("--python", required=True)
    p.add_argument("--node", required=True)
    args = p.parse_args()
    source = Path(args.fixture).read_bytes()
    fixture = json.loads(source)
    expected = {c["id"]: c["expected"] for c in fixture["cases"]}
    python = json.loads(Path(args.python).read_bytes())
    node = json.loads(Path(args.node).read_bytes())
    assert python == expected, "Python actual differs from frozen expected"
    assert node == expected, "Node actual differs from frozen expected"
    assert python == node, "Cross-language mismatch"
    assert Path(args.python).read_bytes() == Path(args.node).read_bytes(), "Report encoding/newline mismatch"
    # Exact comparison includes every canonical byte, length prefix, full framed
    # segment/message and both full MACs, not only the digest or an exception type.
    positive = sum(c["expected"]["status"] == "ok" for c in fixture["cases"])
    negative = len(expected) - positive
    print(
        f"Cross-language: {len(expected)} exact frozen results PASS ({positive} positive, {negative} exact error-code cases)"
    )
    print("Canonical/framing/message hex and both MACs: byte-for-byte equal")
    print("fixture_sha256=" + hashlib.sha256(source).hexdigest())


if __name__ == "__main__":
    main()
