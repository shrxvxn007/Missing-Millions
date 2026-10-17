"""Unsupervised regional comparison and transparent investigation scoring.

All outputs are relative planning signals, never medical need probabilities.
"""
from __future__ import annotations

from typing import Any, Iterable
import numpy as np
from scipy.stats import rankdata, theilslopes
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import RobustScaler

MODEL_VERSION = "isolation-forest-regional-v1"
DEFAULT_SEEDS = (11, 29, 47, 71, 101)
DEFAULT_WEIGHTS = {"access": 0.35, "population": 0.25, "growth": 0.15,
                   "mapping": 0.15, "anomaly": 0.10}
FEATURE_DEFINITIONS = [
    ("population_estimate", "log population estimate", "log"),
    ("building_density", "buildings per square kilometre", "log"),
    ("building_count_change", "absolute building signal change", "signed_log"),
    ("building_growth_percentage", "relative building signal change", "signed_log"),
    ("walking_time_minutes", "estimated walk to mapped facility", "log"),
    ("road_density", "mapped road length per square kilometre", "log"),
    ("road_snap_distance", "connection distance to walking network", "log"),
    ("osm_building_discrepancy", "fraction of satellite estimate unmatched by OSM", "identity"),
]


def temporal_growth(series: dict[str, float | None], minimum_baseline: float = 10) -> dict:
    """Endpoint differences plus robust observed-year slope and persistence.

    Near-zero baselines return null percentages rather than explosive ratios.
    Theil–Sen slope dampens an isolated anomalous annual prediction. Persistence
    is reported only with >=3 actual observations, never interpolated years.
    """
    points = sorted((int(year), float(value)) for year, value in series.items()
                    if value is not None and np.isfinite(value))
    if len(points) < 2:
        return {"building_count_change": None, "building_growth_percentage": None,
                "estimated_change_per_year": None, "growth_persistence": None,
                "growth_observation_count": len(points)}
    years, values = map(np.array, zip(*points))
    change = float(values[-1] - values[0])
    percentage = change / values[0] * 100 if values[0] >= minimum_baseline else None
    slope = float(theilslopes(values, years).slope)
    differences = np.diff(values)
    # Allow a tiny 2% wiggle relative to the series median as prediction noise.
    tolerance = float(max(1.0, np.median(values) * .02))
    persistence = float(np.mean(differences >= -tolerance)) if len(points) >= 3 else None
    return {"building_count_change": round(change, 2),
            "building_growth_percentage": round(percentage, 2) if percentage is not None else None,
            "estimated_change_per_year": round(slope, 2),
            "growth_persistence": round(persistence, 3) if persistence is not None else None,
            "growth_observation_count": len(points)}


def percentile_normalise(values: Iterable[float | None]) -> np.ndarray:
    """Regional empirical ranks, missing stays NaN; identical evidence maps to .5."""
    array = np.array([np.nan if value is None else value for value in values], dtype=float)
    valid = np.isfinite(array)
    result = np.full(array.shape, np.nan)
    if np.sum(valid) == 1:
        result[valid] = .5
    elif np.sum(valid) > 1:
        result[valid] = (rankdata(array[valid], method="average") - 1) / (np.sum(valid) - 1)
    return result


def prepare_features(settlements: list[dict]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Log transforms, explicit median imputation, missing flags, robust scaling."""
    columns = []
    for key, _, transformation in FEATURE_DEFINITIONS:
        values = np.array([np.nan if s.get(key) is None else s[key] for s in settlements], dtype=float)
        if transformation == "log":
            values = np.where(np.isfinite(values), np.log1p(np.maximum(values, 0)), np.nan)
        elif transformation == "signed_log":
            values = np.sign(values) * np.log1p(np.abs(values))
        columns.append(values)
    raw = np.stack(columns, axis=1)
    missing = ~np.isfinite(raw)
    # Explicitly remove wholly unavailable predictors; missingness is retained.
    supported = np.any(~missing, axis=0)
    selected = raw[:, supported]
    names = [definition[1] for definition, keep in zip(FEATURE_DEFINITIONS, supported) if keep]
    if selected.shape[1] == 0:
        return np.zeros((len(settlements), 1)), raw, ["no supported predictors"]
    imputed = SimpleImputer(strategy="median").fit_transform(selected)
    scaled = RobustScaler(quantile_range=(25, 75)).fit_transform(imputed)
    availability_flags = missing.astype(float)
    return np.column_stack((scaled, availability_flags)), raw, names


def fit_anomalies(settlements: list[dict], *, seeds=DEFAULT_SEEDS,
                  minimum_samples: int = 30) -> dict:
    """Fit independent seeded forests; report rank variability as stability.

    Feature comparisons describe deviations from the regional median; they are
    NOT causal or per-tree SHAP explanations of the forest's decision.
    """
    if len(settlements) < minimum_samples:
        reason = f"Anomaly model disabled: {len(settlements)} candidates; minimum {minimum_samples}."
        for settlement in settlements:
            settlement.update(anomaly_score=None, anomaly_stability=None,
                              anomaly_contributors=[], anomaly_status=reason)
        return {"status": "insufficient_samples", "sample_count": len(settlements),
                "minimum_samples": minimum_samples, "reason": reason}
    if len(seeds) < 2:
        raise ValueError("At least two seeds are required for rank stability")
    features, raw, names = prepare_features(settlements)
    ranks = []
    for seed in seeds:
        model = IsolationForest(n_estimators=128, max_samples=min(256, len(settlements)),
                                contamination="auto", random_state=seed, n_jobs=1)
        model.fit(features)
        ranks.append(percentile_normalise(-model.score_samples(features)) * 100)
    rank_matrix = np.stack(ranks)
    scores = rank_matrix.mean(axis=0)
    stability = np.clip(1 - rank_matrix.std(axis=0) / 50, 0, 1)
    supported = np.any(np.isfinite(raw), axis=0)
    medians = np.full(raw.shape[1], np.nan)
    spreads = np.full(raw.shape[1], np.nan)
    medians[supported] = np.nanmedian(raw[:, supported], axis=0)
    q = np.nanpercentile(raw[:, supported], [25, 75], axis=0)
    spreads[supported] = np.maximum(q[1] - q[0], .1)
    deviations = (raw - medians) / spreads
    for index, settlement in enumerate(settlements):
        order = sorted([i for i in range(raw.shape[1]) if np.isfinite(deviations[index, i])],
                       key=lambda i: abs(deviations[index, i]), reverse=True)[:3]
        contributors = [{"feature": FEATURE_DEFINITIONS[i][0], "label": FEATURE_DEFINITIONS[i][1],
                         "direction": "above regional median" if deviations[index, i] >= 0 else "below regional median",
                         "regional_deviation_iqr": round(float(deviations[index, i]), 2),
                         "value": settlement.get(FEATURE_DEFINITIONS[i][0])}
                        for i in order]
        settlement.update(anomaly_score=round(float(scores[index]), 1),
                          anomaly_stability=round(float(stability[index]), 3),
                          anomaly_contributors=contributors, anomaly_status="available",
                          anomaly_rank_range=[round(float(rank_matrix[:, index].min()), 1),
                                              round(float(rank_matrix[:, index].max()), 1)])
    return {"status": "available", "model_version": MODEL_VERSION, "algorithm": "Isolation Forest",
            "sample_count": len(settlements), "seeds": list(seeds), "trees_per_seed": 128,
            "feature_definitions": [{"key": key, "label": label, "transform": transform}
                                    for key, label, transform in FEATURE_DEFINITIONS],
            "preprocessing": "log transforms; regional median imputation; 8 missing flags; robust IQR scaling",
            "stability_definition": "1 minus standard deviation of seeded percentile ranks / 50; not predictive confidence",
            "contributor_definition": "Largest absolute feature deviations from regional medians in IQR units, not causal attribution"}


def score_priorities(settlements: list[dict], weights: dict[str, float] | None = None) -> dict:
    weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    if set(weights) != set(DEFAULT_WEIGHTS) or any(w < 0 for w in weights.values()) or not np.isclose(sum(weights.values()), 1):
        raise ValueError("Five nonnegative priority weights must sum to one")
    keys = {"access": "walking_time_minutes", "population": "population_estimate",
            "growth": "building_count_change", "mapping": "osm_building_discrepancy", "anomaly": "anomaly_score"}
    normalised = {name: percentile_normalise([s.get(key) for s in settlements]) for name, key in keys.items()}
    # Negative growth is not positive evidence for investigating rapid growth.
    normalised["growth"] = percentile_normalise([
        max(0, s["building_count_change"]) if s.get("building_count_change") is not None else None
        for s in settlements])
    scenario_scores = []
    for altered in weights:
        for multiplier in (.8, 1.2):
            scenario = {k: w * (multiplier if k == altered else 1) for k, w in weights.items()}
            total = sum(scenario.values())
            scenario_scores.append(np.array([sum(scenario[k] / total * (normalised[k][i] if np.isfinite(normalised[k][i]) else 0)
                                                for k in keys) * 100 for i in range(len(settlements))]))
    if settlements:
        sensitivity = np.stack(scenario_scores)
        sensitivity_ranks = np.stack([percentile_normalise(row) for row in sensitivity])
    for i, settlement in enumerate(settlements):
        components = {}
        missing = []
        for name, key in keys.items():
            value = normalised[name][i]
            available = bool(np.isfinite(value))
            if not available:
                missing.append(name)
            components[name] = {"raw_value": settlement.get(key), "normalised": round(float(value), 4) if available else None,
                                "weight": weights[name], "contribution": round(float(value) * weights[name] * 100, 2) if available else None}
        score = sum(c["contribution"] or 0 for c in components.values())
        has_access = "access" not in missing
        settlement.update(priority_score=round(score, 1) if has_access else None,
                          priority_components=components,
                          priority_status="available" if not missing else "provisional" if has_access else "access_unknown",
                          priority_missing_components=missing,
                          priority_weight_coverage=round(sum(weights[k] for k in keys if k not in missing), 2),
                          priority_stability=round(float(1 - sensitivity_ranks[:, i].std()), 3) if has_access else None,
                          priority_sensitivity_range=[round(float(sensitivity[:, i].min()), 1), round(float(sensitivity[:, i].max()), 1)] if has_access else None)
    return {"weights": weights, "normalisation": "regional empirical percentile ranks (ties averaged)",
            "missing_policy": "Unknown access disables overall score. Other missing components contribute no points; original weights retained. Incomplete score is provisional, a lower bound under fixed weights.",
            "sensitivity": "Each weight perturbed ±20%, then renormalised; rank agreement is not predictive confidence",
            "purpose": "Relative priority for human investigation; not medical risk or probability of unmet need"}


def recompute_analysis(settlements: list[dict]) -> dict:
    """Recompute after routing enrichment; also usable by CLI without API imports."""
    for settlement in settlements:
        settlement.update(temporal_growth(settlement["building_count_by_year"]))
    anomaly = fit_anomalies(settlements)
    scoring = score_priorities(settlements)
    for settlement in settlements:
        growth = settlement.get("building_growth_percentage")
        walk = settlement.get("walking_time_minutes")
        prefix = "Synthetic demonstration candidate. " if settlement.get("data_mode") == "synthetic" else "Candidate for local investigation. "
        fragments = []
        if growth is not None:
            fragments.append(f"building signal changed {growth:+.0f}% across available observations")
        if walk is not None:
            fragments.append(f"estimated walk from the representative point to a mapped facility is {walk:.0f} minutes")
        else:
            fragments.append("walking accessibility is unknown")
        settlement["explanation"] = prefix + "; ".join(fragments) + ". This point estimate does not represent every resident's access. Validate occupancy, roads and facility records with local partners."
    return {"anomaly": anomaly, "prioritisation": scoring}
