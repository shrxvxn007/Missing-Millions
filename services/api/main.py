"""Run with: uvicorn services.api.main:app --host 127.0.0.1 --port 8000."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from pipeline.ml.reviews import apply_review_overlays, review_queue, train_label_classifier

from .data import DataRepository
from .schemas import (ConfirmedFacilityCreate, OutreachRequest, ReviewCreate,
                       TaskCreate, TaskStatus, TaskUpdate)
from .storage import TaskStore


ROOT = Path(__file__).resolve().parents[2]


GAP_TASKS = {
    "mapping_gap": "Confirm with local partners whether this settlement is known and occupied, and whether the mapped registry should be corrected.",
    "access_gap": "Verify the mapped facility's operating status and whether it actually provides the needed service; ask residents how they currently reach care.",
    "combined_gap": "Conduct one joint visit: confirm occupancy, check the nearest recorded facility's services and ask how residents currently reach care.",
    "none": "No outstanding gap category; confirm the settlement remains represented in the registry and monitor changes.",
    "undetermined": "Registry comparison was unavailable for this region; travel-time evidence alone needs local confirmation before any gap claim.",
}


def suggested_task(gap_type: str | None) -> str:
    return GAP_TASKS.get(gap_type or "undetermined", GAP_TASKS["undetermined"])


def create_app(data_path: str | Path | None = None, db_path: str | Path | None = None,
               web_dist: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="The Missing Millions", version="0.2.0",
                  description="Settlement-scale geographic investigation hypotheses, with explicit provenance, uncertainty and a human feedback loop.")
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
                       allow_credentials=False, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type"])
    selected_path = data_path or os.getenv("DATA_PACKAGE_PATH")
    # Explicit selection exposes one mode. Otherwise discover distinct prepared
    # packages, preferring acquired evidence, without merging their records.
    configured = [DataRepository(selected_path)] if selected_path else [
        DataRepository(ROOT / "data/processed/turkana.json"),
        DataRepository(ROOT / "data/processed/mbale.json"),
        DataRepository(ROOT / "data/processed/demo.json"),
    ]
    tasks = TaskStore(db_path or os.getenv("TASKS_DB_PATH", ROOT / "data/verification.sqlite3"))
    static_root = Path(web_dist or ROOT / "apps/web/dist").resolve()
    app.state.repositories, app.state.tasks = configured, tasks

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail, "error": {"code": exc.status_code, "message": exc.detail}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        details = [{"location": list(item["loc"]), "message": item["msg"], "type": item["type"]} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": details,
                            "error": {"code": 422, "message": "Invalid request", "details": details}})

    def packages() -> list[tuple[DataRepository, dict]]:
        available = configured if selected_path else [repo for repo in configured if repo.path.is_file()]
        if not available:
            available = configured[-1:]  # Return the explicit missing-data error.
        try:
            loaded = [(repo, repo.load()) for repo in available]
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise HTTPException(503, "Data package is unavailable. Run make prepare-demo or configure DATA_PACKAGE_PATH.") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(503, "Data package is invalid or incompatible. Rebuild the selected package and inspect its source manifest.") from exc
        applied = {}
        for repo, package in loaded:
            labels = tasks.latest_labels(repo.region(package)["id"])
            applied[repo.region(package)["id"]] = apply_review_overlays(package["settlements"], labels)
        return loaded

    def region_report(package: dict) -> dict:
        """Notification text about how many review overlays are currently applied."""
        labels = [s.get("review_label") for s in package["settlements"] if s.get("review_label")]
        return {"reviewed_settlements": len(labels),
                "label_counts": {label: labels.count(label) for label in set(labels)}}

    def resolve_region(region_id: str) -> tuple[DataRepository, dict]:
        for repo, result in packages():
            if repo.region(result)["id"] == region_id:
                return repo, result
        raise HTTPException(404, f"Unknown region: {region_id}")

    def region_package(region_id: str) -> dict:
        return resolve_region(region_id)[1]

    def find_settlement(settlement_id: str, result: dict | None = None) -> dict:
        candidates = [result] if result is not None else [item for _, item in packages()]
        for candidate in candidates:
            for settlement in candidate["settlements"]:
                if settlement["id"] == settlement_id:
                    return settlement
        raise HTTPException(404, f"Unknown settlement: {settlement_id}")

    def recompute_with_confirmed_facilities(repository: DataRepository, result: dict,
                                            store: TaskStore, region_id: str, added: dict | None) -> dict:
        """Recompute walking access after locally confirmed facility records.

        The recomputation is a live demonstration that the analysis responds to
        contradictory evidence: adding an operating facility shortens affected
        routes and reprioritises the region with the same transparent policy.
        It never mutates the stored source evidence; adjusted values are
        overlays labelled with the dataset change, and original values remain.
        """
        confirmed = store.confirmed_facilities(region_id)
        if not confirmed:
            return {"facilities": [], "changed_settlements": 0, "settlements": [],
                    "note": "No confirmed facility records have been added yet."}
        facility_payloads = [{"id": facility["id"], "name": facility["name"],
                              "category": facility["category"], "status": facility["status"],
                              "coordinates": facility["coordinates"],
                              "source": facility.get("source", "Confirmed through local review")}
                             for facility in confirmed]
        engine = repository.engine_with(facility_payloads)
        settlements = result["settlements"]
        working = [dict(s) for s in settlements]
        changed = 0
        for settlement, copy in zip(settlements, working):
            before = settlement.get("walking_time_minutes")
            route = engine.route(copy)
            after_status = route["routing_status"]
            after = route["walking_time_minutes"]
            confirmed_ids = {f["id"] for f in facility_payloads}
            overlay = {"routing_status_after_confirmation": after_status,
                       "walking_time_minutes_after_confirmation": after,
                       "walking_time_minutes_before_confirmation": before,
                       "walking_minutes_change": None if after is None or before is None else round(after - before, 1),
                       "routing_status_before_confirmation": settlement.get("routing_status"),
                       "nearest_facility_after": route.get("nearest_mapped_facility_id"),
                       "nearest_facility_is_confirmed": route.get("nearest_mapped_facility_id") in confirmed_ids}
            settlement["facility_confirmation_overlay"] = overlay
            flag = f"recomputed_after_confirmed_facility_{len(facility_payloads)}"
            if flag not in settlement.get("data_quality_flags", []):
                settlement.setdefault("data_quality_flags", []).append(flag)
            if after is not None:
                copy["walking_time_minutes"] = after
            if after_status == "routable" and after is None:
                copy["walking_time_minutes"] = before  # keep regional ranks honest
            if after != before:
                changed += 1
        from pipeline.ml.analysis import score_priorities
        score_priorities(working)
        for settlement, copy in zip(settlements, working):
            settlement["priority_after_confirmation"] = {
                "priority_score": copy.get("priority_score"),
                "priority_status": copy.get("priority_status"),
                "priority_missing_components": copy.get("priority_missing_components"),
                "priority_components": copy.get("priority_components")}
        changes = [{"id": settlement["id"], "display_name": settlement["display_name"],
                    "before_minutes": settlement["facility_confirmation_overlay"]["walking_time_minutes_before_confirmation"],
                    "after_minutes": settlement["facility_confirmation_overlay"]["walking_time_minutes_after_confirmation"],
                    "minutes_change": settlement["facility_confirmation_overlay"]["walking_minutes_change"],
                    "priority_before": settlement.get("priority_score"),
                    "priority_after": (settlement.get("priority_after_confirmation") or {}).get("priority_score"),
                    "population_estimate": settlement.get("population_estimate"),
                    "candidate_gap_type": settlement.get("candidate_gap_type")}
                   for settlement in settlements]
        improved = sorted((change for change in changes
                           if change["minutes_change"] is not None and change["minutes_change"] < -0.05),
                          key=lambda change: change["minutes_change"])
        return {"facilities": facility_payloads, "added": added,
                "changed_settlements": len([c for c in changes if c["priority_before"] != c["priority_after"]]),
                "improved_access": improved, "settlements": changes,
                "assumptions": [
                    "Walking speed 4.2 km/h baseline; confirmed facilities carry the same off-network connector assumptions as mapped facilities.",
                    "Records added through this demo screen are locally confirmed claims used for demonstration; they are not verified by any authority.",
                    "Adjusted values are overlays; original source evidence and first-pass priorities remain visible.",
                    "Recomputed access still describes a representative point, not every resident's journey."]}

    @app.get("/api/health")
    def health():
        try:
            loaded = packages()
            repository, result = loaded[0]
            return {"status": "ok", "application": "The Missing Millions", "data_package": "ready",
                    "region_id": repository.region(result)["id"],
                    "data_mode": result.get("data_mode", result.get("region", {}).get("data_mode", "unknown")),
                    "candidate_count": sum(len(item["settlements"]) for _, item in loaded),
                    "regions": [repo.region(item) for repo, item in loaded]}
        except HTTPException as exc:
            return {"status": "degraded", "application": "The Missing Millions", "data_package": "missing", "detail": exc.detail}

    @app.get("/api/regions")
    def regions():
        return {"regions": [repo.region(result) for repo, result in packages()]}

    @app.get("/api/regions/compare")
    def compare():
        """Side-by-side regional summary; never merges records across packages."""
        import numpy as np
        rows = []
        for repo, result in packages():
            settlements = result["settlements"]
            walks = [s["walking_time_minutes"] for s in settlements if s.get("walking_time_minutes") is not None]
            populations = [s.get("population_estimate") for s in settlements if s.get("population_estimate") is not None]
            gap_counts: dict[str, int] = {}
            for settlement in settlements:
                gap = settlement.get("candidate_gap_type", "undetermined")
                gap_counts[gap] = gap_counts.get(gap, 0) + 1
            label_counts: dict[str, int] = {}
            for settlement in settlements:
                label = settlement.get("review_label")
                if label:
                    label_counts[label] = label_counts.get(label, 0) + 1
            registry = result.get("registry") or {}
            recall = result.get("manifest", {}).get("settlement_registry_recall", {})
            rows.append({
                "region_id": repo.region(result)["id"], "name": repo.region(result)["name"],
                "country": repo.region(result).get("country"), "data_mode": repo.region(result).get("data_mode"),
                "candidate_count": len(settlements),
                "population_estimate": round(sum(populations)) if populations else None,
                "median_walk_minutes": round(float(np.median(walks)), 1) if walks else None,
                "max_walk_minutes": max(walks) if walks else None,
                "routable_count": len(walks),
                "gap_counts": gap_counts, "reviewed_count": sum(label_counts.values()),
                "registry_record_count": len(registry.get("features", [])) if isinstance(registry, dict) else 0,
                "registry_recall": recall.get("recall"), "registry_recall_points": recall.get("registry_points"),
                "region": repo.region(result),
            })
        return {"regions": rows,
                "note": "Comparison of independently prepared packages; every number is a regional aggregate with its own caveats, not a merged analysis."}

    @app.get("/api/regions/{region_id}/overview")
    def overview(region_id: str):
        repository, result = resolve_region(region_id)
        return repository.overview(result)

    @app.get("/api/regions/{region_id}/manifest")
    def manifest(region_id: str):
        return region_package(region_id)["manifest"]

    @app.get("/api/regions/{region_id}/layers")
    def layers(region_id: str):
        repository, result = resolve_region(region_id)
        return repository.layers(result)

    @app.get("/api/regions/{region_id}/blind-test")
    def blind_test(region_id: str, withhold: int = Query(default=10, ge=1, le=200), radius_m: float = Query(default=500, ge=100, le=2000)):
        """Rediscovered intentionally withheld registry settlements, live.

        The omissions are disclosed evaluation artifacts, not discoveries; the
        response states that explicitly for the demo audience.
        """
        result = region_package(region_id)
        from pipeline.evaluate import withheld_recall
        report = withheld_recall(result, withhold=withhold, radius_m=radius_m)
        report["region_id"] = region_id
        return report

    @app.get("/api/regions/{region_id}/settlements")
    def settlements(region_id: str, min_priority: float = Query(default=0, ge=0, le=100)):
        candidates = [s for s in region_package(region_id)["settlements"] if (s.get("priority_score") or 0) >= min_priority]
        return {"settlements": sorted(candidates, key=lambda s: s.get("priority_score") or 0, reverse=True)}

    @app.get("/api/settlements/{settlement_id}/access-profile")
    def access_profile_endpoint(settlement_id: str):
        settlement = find_settlement(settlement_id)
        repository = next((item for item, candidate in packages() if any(
            s["id"] == settlement_id for s in candidate["settlements"])), None)
        if repository is None:
            raise HTTPException(404, f"Unknown settlement: {settlement_id}")
        return repository.access_profile(settlement)

    @app.get("/api/settlements/{settlement_id}")
    def detail(settlement_id: str):
        settlement = dict(find_settlement(settlement_id))
        records = [t for t in tasks.list(settlement["region_id"]) if t["settlement_id"] == settlement_id]
        if records:
            settlement["verification_status"] = records[0]["status"]
        settlement["verification_task_count"] = len(records)
        return settlement

    @app.get("/api/regions/{region_id}/timeline")
    def timeline(region_id: str):
        result = region_package(region_id)
        years = sorted({int(year) for s in result["settlements"] for year in s.get("building_count_by_year", {})})
        return {"years": years, "settlements": [
            {"id": s["id"], "building_count_by_year": s.get("building_count_by_year", {})}
            for s in result["settlements"]],
            "interpretation": "Model-estimated building signal; temporal differences do not prove construction or occupancy."}

    @app.post("/api/outreach/simulate")
    def simulate(request: OutreachRequest):
        repository, result = resolve_region(request.region_id)
        known = {s["id"] for s in result["settlements"]}
        unknown = sorted(set(request.target_settlement_ids) - known)
        if unknown:
            raise HTTPException(422, f"Unknown target settlements in this region: {', '.join(unknown)}")
        engine = repository.get_engine()
        try:
            response = engine.simulate(result["settlements"], request.target_settlement_ids,
                                       request.coverage_minutes, request.locations, request.walking_speed_kmh,
                                       request.fixed_location)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        response["region_id"] = request.region_id
        response["data_mode"] = result.get("data_mode", result.get("region", {}).get("data_mode", "unknown"))
        return response

    @app.post("/api/verification-tasks", status_code=201)
    def create_task(request: TaskCreate):
        result = region_package(request.region_id)
        settlement = find_settlement(request.settlement_id, result)
        return tasks.create(settlement, request.region_id, request.notes, request.status,
                            request.hypothetical_outreach_location.model_dump(mode="json") if request.hypothetical_outreach_location else None)

    @app.get("/api/verification-tasks")
    def list_tasks(region_id: str | None = None, status: TaskStatus | None = None):
        if region_id:
            region_package(region_id)
        return {"tasks": tasks.list(region_id, status)}

    # The export route must precede the task-id route for future GET detail support.
    @app.get("/api/verification-tasks/export")
    def export_tasks(format: Literal["csv", "json", "geojson"] = "csv", region_id: str | None = None):
        if region_id:
            region_package(region_id)
        records = tasks.list(region_id)
        if format == "json":
            return JSONResponse({"tasks": records}, headers={"Content-Disposition": 'attachment; filename="investigation-tasks.json"'})
        if format == "geojson":
            return JSONResponse({"type": "FeatureCollection", "features": [
                {"type": "Feature", "geometry": task["evidence"].get("geometry"),
                 "properties": {k: v for k, v in task.items() if k != "evidence"}} for task in records
            ]}, headers={"Content-Disposition": 'attachment; filename="investigation-tasks.geojson"'})
        stream = io.StringIO(newline="")
        columns = ["id", "settlement_id", "region_id", "status", "notes", "created_at", "updated_at", "longitude", "latitude", "population_estimate", "walking_time_minutes", "priority_score", "evidence_json"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for record in records:
            evidence = record["evidence"]
            center = evidence.get("centroid", [None, None])
            if isinstance(center, dict):
                center = center.get("coordinates", [None, None])
            writer.writerow({**{key: record[key] for key in columns[:7]},
                             "longitude": center[0], "latitude": center[1],
                             **{key: evidence.get(key) for key in columns[9:12]},
                             "evidence_json": json.dumps(evidence)})
        return Response(stream.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="investigation-tasks.csv"'})

    @app.patch("/api/verification-tasks/{task_id}")
    def patch_task(task_id: str, request: TaskUpdate):
        task = tasks.update(task_id, request.model_dump(exclude_unset=True))
        if task is None:
            raise HTTPException(404, f"Unknown verification task: {task_id}")
        return task

    # ---- human feedback loop: labels that change the computed ranking ----

    @app.post("/api/settlements/{settlement_id}/reviews", status_code=201)
    def create_review(settlement_id: str, request: ReviewCreate):
        repository, result = resolve_region(request.region_id)
        settlement = find_settlement(settlement_id, result)
        review = tasks.add_review(settlement, request.region_id, request.label,
                                  request.notes, request.reviewer)
        overlays = apply_review_overlays(result["settlements"], tasks.latest_labels(request.region_id))
        if overlays:
            repository.invalidate_layers()
        return {"review": review, "settlement": find_settlement(settlement_id, result)}

    @app.get("/api/settlements/{settlement_id}/reviews")
    def list_reviews(settlement_id: str):
        settlement = find_settlement(settlement_id)
        return {"settlement_id": settlement_id, "reviews": tasks.reviews(settlement_id=settlement_id),
                "current_label": settlement.get("review_label"),
                "adjustment_reason": settlement.get("adjustment_reason")}

    @app.get("/api/regions/{region_id}/review-queue")
    def get_review_queue(region_id: str, limit: int = Query(default=10, ge=1, le=100)):
        result = region_package(region_id)
        labels = tasks.latest_labels(region_id)
        apply_review_overlays(result["settlements"], labels)
        queue = review_queue(result["settlements"], reviewed_ids=set(labels), limit=limit)
        names = {s["id"]: (s["display_name"], s.get("candidate_gap_type"),
                            s.get("population_estimate"), s.get("walking_time_minutes"))
                 for s in result["settlements"]}
        for item in queue:
            display_name, gap, population, walk = names[item["settlement_id"]]
            item.update({"display_name": display_name, "candidate_gap_type": gap,
                         "population_estimate": population, "walking_time_minutes": walk,
                         "suggested_task": suggested_task(gap)})
        return {"region_id": region_id, "queue": queue,
                "labeled_count": len(labels), "candidate_count": len(result["settlements"]),
                "definition": "Investigation value = regional priority x normalized uncertainty; topping the queue means one more local observation would change the most open conclusions. Not a medical-need score."}

    @app.post("/api/regions/{region_id}/classifier/train")
    def train_classifier(region_id: str):
        result = region_package(region_id)
        labels = tasks.latest_labels(region_id)
        metrics = train_label_classifier(result["settlements"], labels)
        return metrics

    # ---- evidence response: a newly confirmed clinic recomputes access ----

    @app.post("/api/regions/{region_id}/confirmed-facilities", status_code=201)
    def add_confirmed_facility(region_id: str, request: ConfirmedFacilityCreate):
        if request.region_id != region_id:
            raise HTTPException(422, "Region in the URL and body must match")
        repository, result = resolve_region(region_id)
        bbox = result.get("region", {}).get("bbox")
        lon, lat = request.coordinates
        if bbox and not (bbox[0] - .05 <= lon <= bbox[2] + .05 and bbox[1] - .05 <= lat <= bbox[3] + .05):
            raise HTTPException(422, "Confirmed clinic must lie within the study region")
        record = tasks.add_confirmed_facility(region_id, request.name, request.category,
                                              request.status, list(request.coordinates))
        return recompute_with_confirmed_facilities(repository, result, tasks, region_id, added=record)

    @app.get("/api/regions/{region_id}/confirmed-facilities")
    def get_confirmed_facilities(region_id: str):
        region_package(region_id)
        repository, result = resolve_region(region_id)
        return recompute_with_confirmed_facilities(repository, result, tasks, region_id, added=None)

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Unknown API endpoint")
        requested = (static_root / path).resolve()
        if requested.is_relative_to(static_root) and requested.is_file():
            return FileResponse(requested)
        index = static_root / "index.html"
        if index.is_file() and not Path(path).suffix:
            return FileResponse(index)
        raise HTTPException(404, "Frontend is not built. Run npm run build in apps/web, or use the Vite development server.")

    return app


app = create_app()
