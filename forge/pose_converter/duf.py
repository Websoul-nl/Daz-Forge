from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any


def load_duf(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return loads_duf(data)


def loads_duf(data: bytes) -> dict[str, Any]:
    if _is_gzip(data):
        data = gzip.decompress(data)
    return json.loads(data.decode("utf-8"))


def save_duf(payload: dict[str, Any], path: Path, *, compressed: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent="\t", ensure_ascii=False).encode("utf-8")
    if compressed:
        path.write_bytes(gzip.compress(data))
    else:
        path.write_bytes(data)


def _is_gzip(data: bytes) -> bool:
    return data[:2] == b"\x1f\x8b"
