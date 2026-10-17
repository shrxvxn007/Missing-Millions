"""Human-label recalculation, active-learning ranking and a small label classifier.

Reviews recorded by local reviewers are applied as explicit, transparent
overlays over the computed evidence. A label never overwrites the source
evidence snapshot; it adjusts the derived priority and investigation ranking
with a visible reason.

Boundary: a residential/non-residential label from imagery or local contact
cannot establish occupancy by itself, operating clinics, service quality or
actual healthcare access. Those require appropriate local verification.
"""
from __future__ import annotations

from typing import Any
import numpy as np
from sklearn.linear_model import LogisticRegression

from pipeline.ml.analysis import prepare_features, FEATURE_DEFINITIONS

MODEL_VERSION = "review-feedback-logreg-v1"
LABELS = ("residential", "non_residential", "uncertain")


PRIORITY_KEYS = ("priority_score", "priority_components", "priority_status",
                 "priority_missing_components", "priority_weight_coverage",
                 "priority_stability", "priority_sensitivity_range")


def apply_review_overlays(settlements: list[dict], labels: dict[str, str]) -> int:
    """Apply the latest review label per settlement and recompute priorities.

    Drawing on a `non_residential` review:
      - the candidate contributes no population weight in outreach or priority;
      - regional priorities are recomputed once, keeping percentile ranks
        comparable across the whole region (never one-off per candidate);
      - a visible flag records that a local reviewer rejected the settlement.
    A `residential` review strengthens the investigation value; `uncertain`
    keeps the ranking and flags the unresolved disagreement explicitly.
    Returns the number of settlements whose adjusted evidence differs.
    """
    from pipeline.ml.analysis import score_priorities
    changed = 0
    non_residential = [s for s in settlements if labels.get(s["id"]) == "non_residential"]
    recomputed: dict[str, dict] = {}
    if non_residential:
        working = [dict(s) for s in settlements]
        for settlement in working:
            if labels.get(settlement["id"]) == "non_residential":
                settlement["population_estimate"] = None
                for key in PRIORITY_KEYS:
                    settlement.pop(key, None)
        score_priorities(working)
        for settlement in working:
            if labels.get(settlement["id"]) == "non_residential":
                recomputed[settlement["id"]] = {key: settlement[key] for key in PRIORITY_KEYS if key in settlement}
    for settlement in settlements:
        label = labels.get(settlement["id"])
        settlement["review_label"] = label
        if label is None:
            settlement.pop("adjusted_priority", None)
            settlement.pop("adjustment_reason", None)
            continue
        if label == "non_residential":
            adjusted = recomputed.get(settlement["id"], {})
            reason = "A local review recorded this candidate as likely non-residential; population weight removed and regional priorities recomputed."
        elif label == "residential":
            adjusted = {}
            reason = "A local review recorded this candidate as likely residential; ranking retained and investigation value increased."
        else:
            adjusted = {}
            reason = "A local review marked this candidate uncertain; original ranking retained and the case kept high in the review queue."
        settlement["adjusted_priority"] = adjusted or None
        settlement["adjustment_reason"] = reason
        settlement["effective_population_estimate"] = None if label == "non_residential" else settlement.get("population_estimate")
        flags = settlement.get("data_quality_flags", [])
        if f"review_label_{label}" not in flags:
            flags.append(f"review_label_{label}")
        changed += 1
    return changed


def investigation_value(settlement: dict) -> dict:
    """Active-learning value: how much one more observation could change a decision.

    High when a consequential priority coexists with weak evidence, an open
    question (uncertain settlement or nearby possibly-undocumented care), or a
    gap classification that locals could quickly resolve.
    """
    priority = settlement.get("priority_score")
    adjusted = (settlement.get("adjusted_priority") or {}).get("priority_score", priority)
    base = adjusted if adjusted is not None else 0.0
    uncertainty = 0.0
    missing = settlement.get("priority_missing_components") or []
    uncertainty += 0.25 * min(len(missing), 3) / 3
    if settlement.get("routing_status") != "routable":
        uncertainty += 0.2
    if settlement.get("record_match_status") in ("unmatched", "ambiguous"):
        uncertainty += 0.2
    if settlement.get("candidate_gap_type") in ("combined_gap", "mapping_gap", "access_gap"):
        uncertainty += 0.15
    if settlement.get("review_label") == "uncertain":
        uncertainty += 0.1
    if settlement.get("building_signal_strength") == "sparse_retained_for_review":
        uncertainty += 0.1
    value = base * np.clip(uncertainty, 0, 1)
    factors = set()
    if missing:
        factors.add("missing_priority_components")
    if settlement.get("routing_status") != "routable":
        factors.add("routing_unknown")
    if settlement.get("record_match_status") in ("unmatched", "ambiguous"):
        factors.add(f"registry_{settlement.get('record_match_status')}")
    if settlement.get("candidate_gap_type") in ("combined_gap", "mapping_gap", "access_gap"):
        factors.add(settlement["candidate_gap_type"])
    return {"settlement_id": settlement["id"], "investigation_value": round(float(value), 2),
            "priority": base, "uncertainty": round(float(np.clip(uncertainty, 0, 1)), 3),
            "unresolved_factors": sorted(factors)}


def review_queue(settlements: list[dict], *, reviewed_ids: set[str], limit: int = 10) -> list[dict]:
    """Rank unreviewed candidates by investigation value, strongest first.

    Sparse retained signals and uncertain classified candidates rank ahead of
    already-confirmed candidates even at lower priority: reviewing them changes
    more of the open conclusion.
    """
    unreviewed = [s for s in settlements if s["id"] not in reviewed_ids]
    ranked = sorted((investigation_value(s) for s in unreviewed),
                    key=lambda value: (-value["investigation_value"], -value["priority"]))
    for index, item in enumerate(ranked):
        item["queue_rank"] = index + 1
    return ranked[:max(1, limit)]


def train_label_classifier(settlements: list[dict], labels: dict[str, str],
                           *, minimum_labeled: int = 10, holdout_fraction: float = 0.25,
                           seed: int = 7) -> dict:
    """Fit a simple logistic classifier on recorded review labels.

    Two classes only: residential versus non_residential; `uncertain` labels
    are excluded. A spatially random split is still optimistic (nearby
    candidates share conditions), which the output states explicitly.
    Returns coefficients so the model stays inspectable and reproducible.
    """
    labeled = [s for s in settlements if labels.get(s["id"]) in ("residential", "non_residential")]
    counts = {"residential": sum(1 for s in settlements if labels.get(s["id"]) == "residential"),
              "non_residential": sum(1 for s in settlements if labels.get(s["id"]) == "non_residential"),
              "uncertain": sum(1 for s in settlements if labels.get(s["id"]) == "uncertain")}
    if len(labeled) < minimum_labeled or min(counts["residential"], counts["non_residential"]) < 2:
        return {"status": "insufficient_labels", "model_version": MODEL_VERSION,
                "labeled_samples": len(labeled), "label_counts": counts,
                "minimum_labeled": minimum_labeled,
                "reason": f"Train a feedback classifier with at least {minimum_labeled} labelled candidates (>=2 per class); currently {counts}.",
                "note": "Until then, review priorities come from the transparent investigation-value heuristic, not a trained model."}
    features, _, names = prepare_features(labeled)
    targets = np.array([1 if labels[s["id"]] == "residential" else 0 for s in labeled])
    # Drop missing-flag columns (they tell the trainer about missing evidence,
    # not about settlements) and constants so coefficients stay interpretable.
    feature_width = len(FEATURE_DEFINITIONS)
    core = features[:, :feature_width] if features.shape[1] >= feature_width else features
    keep = ~np.all(core == core[0:1], axis=0)
    core = core[:, keep]
    names = [name for name, use in zip(names, keep) if use]
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(labeled))
    holdout = max(1, int(round(len(labeled) * holdout_fraction)))
    test_index, train_index = order[:holdout], order[holdout:]
    model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed)
    model.fit(core[train_index], targets[train_index])
    train_accuracy = float(model.score(core[train_index], targets[train_index]))
    test_accuracy = float(model.score(core[test_index], targets[test_index])) if len(test_index) >= 2 else None
    probabilities = model.predict_proba(core)[:, 1]
    for index, settlement in enumerate(labeled):
        settlement["classifier_residential_probability"] = round(float(probabilities[index]), 4)
    return {"status": "available", "model_version": MODEL_VERSION, "algorithm": "LogisticRegression",
            "labeled_samples": len(labeled), "label_counts": counts,
            "held_out_samples": len(test_index),
            "train_accuracy": round(train_accuracy, 3),
            "held_out_accuracy": round(test_accuracy, 3) if test_accuracy is not None else None,
            "coefficients": [{"feature": names[i] if i < len(names) else f"feature_{i}",
                              "weight": round(float(weight), 4)}
                             for i, weight in enumerate(model.coef_[0])],
            "positive_class": "residential",
            "generalisation_warning": "Labels come from nearby candidates sharing imagery conditions; accuracies are optimistic and not calibrated probabilities of occupancy or need.",
            "boundary": "Imagery or local-contact labels cannot establish occupancy, operating clinics or actual access; treat probabilities as one review aid."}
