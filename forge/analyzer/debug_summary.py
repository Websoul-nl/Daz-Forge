from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from forge.analyzer.inference import infer_metadata
from forge.analyzer.inventory import classify_inventory
from forge.analyzer.review_contract import build_review_contract, contract_to_dict
from forge.analyzer.source import scan_source


def analyze_source_to_summary(path: Path) -> str:
    scan = scan_source(path)
    inventory = classify_inventory(scan)
    inference = infer_metadata(scan, inventory)
    contract = build_review_contract(scan, inventory, inference)
    return contract_to_summary(contract_to_dict(contract))


def contract_to_summary(payload: dict) -> str:
    product = payload["product"]
    rows = payload["rows"]
    lines = [
        "Daz Forge Analysis Summary",
        f"Source: {product['source_path']}",
        f"Product type: {product['product_type']}",
        f"Artist state: {product['artist_state']}",
        f"Smart Content rows: {product['smart_content_count']}",
        f"Warnings: {len(payload['warnings'])}",
        f"Hard blockers: {len(payload['hard_blockers'])}",
        "",
        "Rows:",
    ]
    for row in rows[:20]:
        categories = ", ".join(row["final"]["categories"])
        lines.append(f"- {row['path']} | {row['final']['content_type']} | {categories}")
    if len(rows) > 20:
        lines.append(f"- ... {len(rows) - 20} more rows")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a Daz Forge analyzer review summary.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--json", action="store_true", help="Print the full review contract JSON.")
    args = parser.parse_args(argv)

    scan = scan_source(args.source)
    inventory = classify_inventory(scan)
    inference = infer_metadata(scan, inventory)
    contract = build_review_contract(scan, inventory, inference)
    payload = contract_to_dict(contract)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(contract_to_summary(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
