import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import { Map as LibreMap, GeoJSONSource } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
maplibregl.setWorkerUrl(workerUrl);
import { Plus, Minus, LocateFixed, Compass } from "lucide-react";
import type { Region, Settlement, Layers, Simulation } from "../types";
const empty = { type: "FeatureCollection" as const, features: [] };
interface Props {
  region: Region;
  layers: Layers;
  settlements: Settlement[];
  selected: Settlement | null;
  revealed: boolean;
  year: number;
  simulation: Simulation | null;
  showRoads: boolean;
  showCells: boolean;
  showFacilities: boolean;
  showRegistry: boolean;
  showSatellite: boolean;
  pickMode: boolean;
  confirmedFacilities: any[];
  onSelect: (id: string) => void;
  reset: number;
  stage: number;
  onMoveOutreach: (point: [number, number]) => void;
  onPickPoint: (point: [number, number]) => void;
}
export default function GeoMap(p: Props) {
  const holder = useRef<HTMLDivElement>(null),
    map = useRef<LibreMap | null>(null),
    markers = useRef<maplibregl.Marker[]>([]),
    callback = useRef(p.onSelect),
    outreachCallback = useRef(p.onMoveOutreach);
  const [ready, setReady] = useState(false),
    [failed, setFailed] = useState(false),
    [cursor, setCursor] = useState<[number, number]>(p.region.center);
  callback.current = p.onSelect;
  outreachCallback.current = p.onMoveOutreach;
  const pickCallback = useRef(p.onPickPoint);
  pickCallback.current = p.onPickPoint;
  const fit = () => {
    const b = p.region.bbox;
    map.current?.fitBounds(
      [
        [b[0], b[1]],
        [b[2], b[3]],
      ],
      {
        padding: {
          top: 80,
          bottom: 100,
          left: window.innerWidth > 1000 ? 260 : 35,
          right: 40,
        },
        duration: 900,
      },
    );
  };
  useEffect(() => {
    if (!holder.current) return;
    let m: LibreMap;
    try {
      m = new maplibregl.Map({
        container: holder.current,
        style: {
          version: 8,
          sources: {},
          layers: [
            {
              id: "background",
              type: "background",
              paint: { "background-color": "#111c1e" },
            },
          ],
        },
        center: p.region.center,
        zoom: 11,
        attributionControl: false,
        renderWorldCopies: false,
        maxZoom: 17,
        minZoom: 7,
      });
    } catch {
      setFailed(true);
      return;
    }
    map.current = m;
    m.on("load", () => {
      for (const name of [
        "grid",
        "roads",
        "cells",
        "settlements",
        "selected",
        "route",
        "coverage",
        "outreach",
        "registry",
      ])
        m.addSource(name, { type: "geojson", data: empty });
      const b = p.region.bbox,
        features: any[] = [];
      for (let x = Math.floor(b[0] * 50) / 50; x < b[2] + 0.02; x += 0.02)
        features.push({
          type: "Feature",
          properties: {},
          geometry: {
            type: "LineString",
            coordinates: [
              [x, b[1] - 0.1],
              [x, b[3] + 0.1],
            ],
          },
        });
      for (let y = Math.floor(b[1] * 50) / 50; y < b[3] + 0.02; y += 0.02)
        features.push({
          type: "Feature",
          properties: {},
          geometry: {
            type: "LineString",
            coordinates: [
              [b[0] - 0.1, y],
              [b[2] + 0.1, y],
            ],
          },
        });
      (m.getSource("grid") as GeoJSONSource).setData({
        type: "FeatureCollection",
        features,
      });
      m.addLayer({
        id: "grid",
        type: "line",
        source: "grid",
        paint: {
          "line-color": "#5a777a",
          "line-width": 0.6,
          "line-opacity": 0.13,
        },
      });
      if (!m.getSource("satellite"))
        m.addSource("satellite", {
          type: "raster",
          tiles: [
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
          ],
          tileSize: 256,
          attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
          minzoom: 6,
          maxzoom: 17,
        });
      m.addLayer({
        id: "satellite",
        type: "raster",
        source: "satellite",
        paint: { "raster-opacity": 1 },
      });
      m.addLayer({
        id: "registry",
        type: "circle",
        source: "registry",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 2.5, 14, 4.5],
          "circle-color": "#e8c34e",
          "circle-stroke-color": "#7a5f22",
          "circle-stroke-width": 1,
          "circle-opacity": 0.85,
        },
      });
      m.addLayer({
        id: "road-casing",
        type: "line",
        source: "roads",
        paint: {
          "line-color": "#061013",
          "line-width": 5,
          "line-opacity": 0.8,
        },
      });
      m.addLayer({
        id: "roads",
        type: "line",
        source: "roads",
        paint: {
          "line-color": "#6f8689",
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.9, 15, 2.5],
          "line-opacity": 0.35,
        },
      });
      m.addLayer({
        id: "cells",
        type: "fill",
        source: "cells",
        paint: {
          "fill-color": [
            "interpolate",
            ["linear"],
            ["coalesce", ["get", "growth"], 0],
            0,
            "#72a494",
            60,
            "#dbb279",
            200,
            "#eab075",
          ],
          "fill-opacity": [
            "interpolate",
            ["linear"],
            ["coalesce", ["get", "count"], 0],
            0,
            0.08,
            15,
            0.24,
            80,
            0.65,
          ],
        },
      });
      m.addLayer({
        id: "cell-lines",
        type: "line",
        source: "cells",
        paint: {
          "line-color": "#e3cda1",
          "line-width": 0.45,
          "line-opacity": 0.25,
        },
      });
      m.addLayer({
        id: "settlements",
        type: "fill",
        source: "settlements",
        paint: {
          "fill-color": [
            "case",
            [">=", ["coalesce", ["get", "priority_score"], 0], 65],
            "#e8b886",
            "#9bbca4",
          ],
          "fill-opacity": 0.12,
        },
      });
      m.addLayer({
        id: "settlement-line",
        type: "line",
        source: "settlements",
        paint: {
          "line-color": [
            "case",
            [">=", ["coalesce", ["get", "priority_score"], 0], 65],
            "#e8b886",
            "#9bbca4",
          ],
          "line-width": 1,
          "line-opacity": 0.5,
        },
      });
      m.addLayer({
        id: "coverage",
        type: "line",
        source: "coverage",
        paint: {
          "line-color": "#6fa8f5",
          "line-width": 4,
          "line-opacity": 0.8,
        },
      });
      m.addLayer({
        id: "route",
        type: "line",
        source: "route",
        paint: {
          "line-color": "#89bfc7",
          "line-width": 3,
          "line-dasharray": [2, 2],
          "line-opacity": 0.9,
        },
      });
      m.addLayer({
        id: "selected-glow",
        type: "line",
        source: "selected",
        paint: {
          "line-color": "#efc98b",
          "line-width": 9,
          "line-blur": 9,
          "line-opacity": 0.8,
        },
      });
      m.addLayer({
        id: "selected",
        type: "line",
        source: "selected",
        paint: { "line-color": "#f4d39f", "line-width": 2 },
      });
      m.on("click", "settlements", (e) => {
        const id = e.features?.[0]?.properties?.id;
        if (id) callback.current(String(id));
      });
      m.on("mouseenter", "settlements", () => {
        m.getCanvas().style.cursor = "pointer";
      });
      m.on("mouseleave", "settlements", () => {
        m.getCanvas().style.cursor = "";
      });
      m.on("mousemove", (e) => setCursor([e.lngLat.lng, e.lngLat.lat]));
      m.on("click", (e) => {
        // Pick-mode clicks ignore feature clicks; feature handlers above run too.
        pickCallback.current([e.lngLat.lng, e.lngLat.lat]);
      });
      setReady(true);
    });
    m.on("error", (e) => {
      console.warn("Geographic layer error", e.error?.message);
    });
    return () => {
      markers.current.forEach((x) => x.remove());
      m.remove();
      map.current = null;
      setReady(false);
    };
  }, [p.region.id]);
  useEffect(() => {
    if (ready) fit();
  }, [ready, p.reset]);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    (m.getSource("roads") as GeoJSONSource).setData(p.layers.roads as any);
    (m.getSource("settlements") as GeoJSONSource).setData(
      (p.revealed ? p.layers.settlements : empty) as any,
    );
    const registry = p.layers.registry ?? empty;
    (m.getSource("registry") as GeoJSONSource).setData(
      p.showRegistry ? (registry as any) : empty,
    );
    m.setLayoutProperty(
      "satellite",
      "visibility",
      p.showSatellite ? "visible" : "none",
    );
    m.getCanvas().style.cursor = p.pickMode ? "crosshair" : "";
    const cells = {
      ...p.layers.cells,
      features: p.layers.cells.features.map((f) => {
        const series = f.properties?.building_count_by_year ?? {};
        const count = Number(
          series[String(p.year)] ??
            f.properties?.[`count_${p.year}`] ??
            f.properties?.building_count ??
            0,
        );
        return {
          ...f,
          properties: {
            ...f.properties,
            count,
            growth: Math.max(0, count - Number(series["2016"] ?? 0)),
          },
        };
      }),
    };
    (m.getSource("cells") as GeoJSONSource).setData(
      (p.revealed && p.showCells ? cells : empty) as any,
    );
    (m.getSource("selected") as GeoJSONSource).setData(
      p.selected && p.revealed
        ? {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                properties: {},
                geometry: p.selected.geometry,
              },
            ],
          }
        : empty,
    );
    const route =
      p.selected?.route_geometry ?? p.selected?.walking_route_geometry;
    (m.getSource("route") as GeoJSONSource).setData(
      route && p.revealed
        ? {
            type: "FeatureCollection",
            features: [{ type: "Feature", properties: {}, geometry: route }],
          }
        : empty,
    );
    (m.getSource("coverage") as GeoJSONSource).setData(
      p.simulation?.coverage_network ?? empty,
    );
    m.setLayoutProperty(
      "roads",
      "visibility",
      p.showRoads ? "visible" : "none",
    );
    m.setLayoutProperty(
      "road-casing",
      "visibility",
      p.showRoads ? "visible" : "none",
    );
    markers.current.forEach((x) => x.remove());
    markers.current = [];
    if (p.showFacilities)
      p.layers.facilities.features
        .filter((f) => {
          const [x, y] = f.geometry.coordinates,
            b = p.region.bbox;
          return (
            (x >= b[0] - 0.01 &&
              x <= b[2] + 0.01 &&
              y >= b[1] - 0.01 &&
              y <= b[3] + 0.01) ||
            f.properties.id === p.selected?.nearest_mapped_facility_id
          );
        })
        .forEach((f) => {
          const el = document.createElement("button");
          el.className = "facility-marker";
          el.textContent = "+";
          el.title = f.properties.name ?? "Mapped facility";
          el.setAttribute("aria-label", el.title);
          el.addEventListener("click", () =>
            new maplibregl.Popup({ offset: 15, closeButton: false })
              .setLngLat(f.geometry.coordinates)
              .setText(
                `${el.title} · ${p.region.data_mode === "synthetic" ? "synthetic facility" : "mapped facility"}`,
              )
              .addTo(m),
          );
          markers.current.push(
            new maplibregl.Marker({ element: el })
              .setLngLat(f.geometry.coordinates)
              .addTo(m),
          );
        });
    if (p.revealed)
      p.settlements.forEach((s, i) => {
        const gapClass =
          s.candidate_gap_type === "combined_gap"
            ? "gap-combined"
            : s.candidate_gap_type === "mapping_gap"
              ? "gap-mapping"
              : s.candidate_gap_type === "access_gap"
                ? "gap-access"
                : "";
        const el = document.createElement("button");
        el.className = `settlement-marker ${s.id === p.selected?.id ? "active" : ""} ${(s.priority_score ?? 0) >= 65 ? "priority" : ""} ${gapClass}`;
        el.style.animationDelay = `${Math.min(i * 25, 900)}ms`;
        const dot = document.createElement("span");
        dot.className = "marker-dot";
        el.append(dot);
        if (i < 5) {
          const label = document.createElement("span");
          label.className = "marker-label";
          label.textContent = s.display_name;
          el.append(label);
        }
        el.setAttribute("aria-label", `Select ${s.display_name}`);
        const gapLabel = s.candidate_gap_type?.replaceAll("_", " ");
        el.title = `${s.display_name} · investigation priority ${Math.round(s.priority_score ?? 0)}${gapLabel && gapLabel !== "none" ? ` · ${gapLabel}` : ""}`;
        el.onclick = () => callback.current(s.id);
        markers.current.push(
          new maplibregl.Marker({ element: el }).setLngLat(s.centroid).addTo(m),
        );
      });
    (p.confirmedFacilities ?? []).forEach((f: any) => {
      const el = document.createElement("button");
      el.className = "facility-marker confirmed";
      el.textContent = "+";
      el.title = `${f.name} · confirmed through local review`;
      el.setAttribute("aria-label", el.title);
      el.addEventListener("click", () =>
        new maplibregl.Popup({ offset: 15, closeButton: false })
          .setLngLat(f.coordinates)
          .setText(`${el.title}`)
          .addTo(m),
      );
      markers.current.push(
        new maplibregl.Marker({ element: el }).setLngLat(f.coordinates).addTo(m),
      );
    });
    p.simulation?.locations.forEach((point, i) => {
      const el = document.createElement("div");
      el.className = "outreach-marker";
      el.title = "Drag to evaluate another hypothetical location";
      el.innerHTML = `<span>✚</span><b>Hypothetical stop ${i + 1}</b>`;
      const marker = new maplibregl.Marker({ element: el, draggable: true })
        .setLngLat(point.coordinates)
        .addTo(m);
      marker.on("dragend", () => {
        const pos = marker.getLngLat();
        marker.setLngLat(point.coordinates);
        outreachCallback.current([pos.lng, pos.lat]);
      });
      markers.current.push(marker);
    });
  }, [
    ready,
    p.layers,
    p.revealed,
    p.year,
    p.selected,
    p.simulation,
    p.showRoads,
    p.showCells,
    p.showFacilities,
    p.showRegistry,
    p.showSatellite,
    p.pickMode,
    p.confirmedFacilities,
    p.settlements,
  ]);
  useEffect(() => {
    if (ready && p.selected && p.revealed)
      map.current?.easeTo({
        center: p.selected.centroid,
        zoom: Math.max(
          12.1,
          Math.min(
            14.4,
            12.1 + Math.log2(0.225 / (p.region.bbox[2] - p.region.bbox[0])),
          ),
        ),
        padding: {
          left: window.innerWidth > 1000 ? 230 : 0,
          right: 0,
          top: 70,
          bottom: 0,
        },
        duration: 1300,
      });
  }, [ready, p.selected?.id, p.revealed]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !p.simulation?.locations.length) return;
    const bounds = new maplibregl.LngLatBounds();
    const positions: [number, number][] = p.simulation.locations.map(
      (point) => point.coordinates,
    );
    if (p.selected) positions.push(p.selected.centroid);
    p.simulation.settlements
      .filter((s) => s.newly_covered)
      .forEach((s) => {
        const settlement = p.settlements.find((v) => v.id === s.id);
        if (settlement) positions.push(settlement.centroid);
      });
    positions.forEach((point) => bounds.extend(point));
    const mobile = window.innerWidth < 620;
    m.fitBounds(bounds, {
      padding: {
        left: window.innerWidth > 1000 ? 280 : 25,
        right: 55,
        top: mobile ? 80 : 100,
        bottom: mobile ? 125 : 190,
      },
      maxZoom: Math.max(
        12.5,
        Math.min(
          14.5,
          12.5 + Math.log2(0.225 / (p.region.bbox[2] - p.region.bbox[0])),
        ),
      ),
      duration: 800,
    });
  }, [ready, p.simulation]);
  return (
    <>
      <div
        className="map-canvas"
        ref={holder}
        aria-label="Interactive geographic analysis map"
      />
      {failed && (
        <div className="map-error">
          WebGL is unavailable. Settlement evidence and analysis remain
          available in the panel.
        </div>
      )}
      <div className="map-vignette" />
      <div className="map-controls">
        <button
          title="Zoom in"
          aria-label="Zoom in"
          onClick={() => map.current?.zoomIn()}
        >
          <Plus size={17} />
        </button>
        <button
          title="Zoom out"
          aria-label="Zoom out"
          onClick={() => map.current?.zoomOut()}
        >
          <Minus size={17} />
        </button>
        <button
          title="Reset map view"
          aria-label="Reset map view"
          onClick={fit}
        >
          <LocateFixed size={17} />
        </button>
        <button
          title="Reset north"
          aria-label="Reset north"
          onClick={() => map.current?.resetNorth()}
        >
          <Compass size={17} />
        </button>
      </div>
      <div className="map-coordinates">
        {cursor[1].toFixed(4)}° N &nbsp; {cursor[0].toFixed(4)}° E{" "}
        <span>WGS 84 · LOCAL GEOGRAPHIC LAYERS</span>
      </div>
      <div className="north-arrow">
        <span>N</span>
        <i /> <small>2 km reference grid</small>
      </div>
    </>
  );
}
