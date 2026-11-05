"""Turn pytest JUnit failures into GitHub Actions annotations."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_ANNOTATIONS = 10
MAX_MESSAGE = 1200


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "pytest.xml")
    if not path.is_file():
        print(f"::error::missing pytest report: {path}")
        return 1

    failures: list[tuple[str, str, str]] = []
    for case in ET.parse(path).iter("testcase"):
        node = case.find("failure")
        if node is None:
            node = case.find("error")
        if node is None:
            continue
        message = (node.get("message") or node.text or "").strip()
        failures.append(
            (case.get("classname", ""), case.get("name", ""), message)
        )

    print(f"failed tests: {len(failures)}")
    for classname, name, message in failures[:MAX_ANNOTATIONS]:
        text = " ".join(message.split())[:MAX_MESSAGE]
        print(f"::error::{classname}::{name}::{text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
