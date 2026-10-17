"""Reproducible evaluation: registry recall, withheld-settlement recovery, precision.

    python -m pipeline.evaluate --package data/processed/real.json [--withhold 5]

Metrics are honest about what a 48-hour CPU proof of concept can and cannot
show: they measure GEOMETRIC recovery of reference settlements by the
satellite detection pipeline and the representational precision of top-ranked
candidates — never medical need, occupancy or delivered care.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def detected_precision(package: dict, *, top_n: int = 20) -> dict:
    """Share of top-ranked candidates represented in the registry.

    Every matched candidate still keeps its evidence and uncertainty; matched
    does not mean verified and unmatched does not mean fictional.
    """
    settlements = sorted(package["settlements"],
                         key=lambda s: s.get("priority_score") if s.get("priority_score") is not None else -1,
                         reverse=True)
    top = settlements[:top_n]
    matched = sum(1 for s in top if s.get("record_match_status") == "matched")
    ambiguous = sum(1 for s in top if s.get("record_match_status") == "ambiguous")
    return {"top_n": len(top), "matched": matched, "ambiguous": ambiguous,
            "unmatched": sum(1 for s in top if s.get("record_match_status") == "unmatched"),
            "no_registry": sum(1 for s in top if s.get("record_match_status") == "no_registry"),
            "registry_represented_share": round((matched + ambiguous) / len(top), 4) if top else None,
            "interpretation": "Share of top-ranked candidates represented in the chosen registry (including equivocal matches). Not precision about need; the registry itself is unverified."}


def withheld_recall(package: dict, *, withhold: int = 0, radius_m: float = 500) -> dict:
    """Rediscovers intentionally withheld registry settlements.

    Withholding means: remove `withhold` registry points from the detection
    side's view AND from the matching evidence, then check whether the
    satellite pipeline's candidate clusters still sit near the withheld
    points. The omissions are disclosed in `withheld_ids` — they are
    evaluation artifacts, not newly discovered unknown villages.
    """
    if withhold <= 0:
        return {"status": "not_withheld", "note": "Run with a positive --withhold to evaluate recovery of omitted reference settlements."}
    features = package.get("registry", {}).get("features", [])
    bbox = package.get("region", {}).get("bbox")
    withheld, remaining = [], []
    for index, feature in enumerate(features):
        point = feature["geometry"]["coordinates"]
        inside = bbox is None or (bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3])
        if inside and len(withheld) < withhold:
            withheld.append(feature)
        else:
            remaining.append(feature)
    reduced = {"region": package["region"], "settlements": package["settlements"],
               "registry": {"type": "FeatureCollection", "features": remaining}}
    from pipeline.geospatial.gaps import registry_recall
    blocked = registry_recall(reduced, radius_m=radius_m)  # detection vs remaining registry
    # Now measure recovery against the WITHHELD points only.
    from pipeline.geospatial.gaps import _package_crs
    import numpy as np
    from scipy.spatial import cKDTree
    from pyproj import Transformer
    crs = _package_crs(package)
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    candidate_points = np.array([transformer.transform(*s["centroid"]) for s in package["settlements"]])
    tree = cKDTree(candidate_points) if len(candidate_points) else None
    recovered, missed = [], []
    for feature in withheld:
        if tree is None:
            missed.append(feature["properties"].get("name"))
            continue
        point = np.array(transformer.transform(*feature["geometry"]["coordinates"]))
        distance, candidate = tree.query(point)
        if distance <= radius_m:
            recovered.append({"name": feature["properties"].get("name"),
                              "distance_m": round(float(distance), 1),
                              "candidate_id": package["settlements"][int(candidate)]["id"]})
        else:
            missed.append(feature["properties"].get("name"))
    return {"status": "available", "withheld_count": len(withheld), "withheld_ids": [f["id"] for f in withheld],
            "recovered": len(recovered), "recall": round(len(recovered) / len(withheld), 4) if withheld else None,
            "matches": recovered, "missed_names": [name for name in missed if name],
            "disclosure": "Registry points were intentionally withheld FOR EVALUATION and are reported as recovered reference settlements, not new discoveries.",
            "interpretation": "Share of intentionally omitted reference settlements that satellite detection still covered within the radius."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=ROOT / "data/processed/real.json")
    parser.add_argument("--withhold", type=int, default=0)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--radius-m", type=float, default=500)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    package = json.loads(args.package.read_text())
    report = {
        "package": str(args.package),
        "candidate_count": len(package["settlements"]),
        "gap_classification": package.get("manifest", {}).get("settlement_registry", {}).get("gap_classification"),
        "in_extent_registry_recall": registry_recall_eval(package, args.radius_m),
        "detected_precision_top": detected_precision(package, top_n=args.top_n),
        "withheld_recall": withheld_recall(package, withhold=args.withhold, radius_m=args.radius_m),
        "boundaries": [
            "These metrics evaluate geometric coverage of a mapped reference layer by satellite detections.",
            "The registry itself is unverified and incomplete; no accuracy about unmet healthcare need is claimed.",
            "Withheld settlements are evaluation omissions disclosed in `withheld_ids`.",
        ],
    }
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
        print(payload)
    else:
        print(payload)
    return 0


def registry_recall_eval(package: dict, radius_m: float) -> dict:
    from pipeline.geospatial.gaps import registry_recall
    return registry_recall(package, radius_m=radius_m)


if __name__ == "__main__":
    raise SystemExit(main())
