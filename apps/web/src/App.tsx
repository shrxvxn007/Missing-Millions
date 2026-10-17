import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  ArrowLeft,
  Play,
  Pause,
  RotateCcw,
  Globe2,
  Layers3,
  SlidersHorizontal,
  Satellite,
  MapPin,
  Activity,
  ClipboardList,
  Info,
  X,
  ChevronDown,
  Check,
  Search,
  Plus,
  Minus,
  Download,
  LoaderCircle,
  Footprints,
  Route,
  Users,
  CheckCircle2,
  ExternalLink,
  GitCompare,
  FlaskConical,
} from "lucide-react";
import GeoMap from "./components/GeoMap";
import Evidence from "./components/Evidence";
import Methodology from "./components/Methodology";
import { api, number, minutes, download } from "./lib/api";
import type { Region, Settlement, Layers, Simulation, Task } from "./types";
const scenes = [
  {
    title: "The world we think we know",
    text: "Planning starts with the information we have.",
  },
  {
    title: "Look again",
    text: "Satellite-derived signals can reveal where maps may be incomplete.",
  },
  {
    title: "The possible gap",
    text: "Now we have somewhere specific to investigate.",
  },
  {
    title: "Flip the script",
    text: "What if care went to them? Explore a hypothetical outreach stop.",
  },
];
type Modal = "method" | "data" | "tasks" | "create" | "settings" | "compare" | null;
export default function App() {
  const [regions, setRegions] = useState<Region[]>([]),
    [region, setRegion] = useState<Region | null>(null),
    [layers, setLayers] = useState<Layers | null>(null),
    [settlements, setSettlements] = useState<Settlement[]>([]),
    [manifest, setManifest] = useState<any>(null),
    [summary, setSummary] = useState<any>({});
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [revealed, setRevealed] = useState(false),
    [selected, setSelected] = useState<Settlement | null>(null),
    [year, setYear] = useState(2023),
    [panel, setPanel] = useState<"candidates" | "evidence">("candidates"),
    [modal, setModal] = useState<Modal>(null),
    [reset, setReset] = useState(0);
  const [simulation, setSimulation] = useState<Simulation | null>(null),
    [busy, setBusy] = useState(false),
    [threshold, setThreshold] = useState(30),
    [locations, setLocations] = useState(1),
    [speed, setSpeed] = useState(4.2),
    [targetAll, setTargetAll] = useState(false);
  const [showRoads, setShowRoads] = useState(true),
    [showCells, setShowCells] = useState(true),
    [showFacilities, setShowFacilities] = useState(true),
    [showRegistry, setShowRegistry] = useState(true),
    [showSatellite, setShowSatellite] = useState(true),
    [layerMenu, setLayerMenu] = useState(false),
    [regionMenu, setRegionMenu] = useState(false);
  const [pickMode, setPickMode] = useState(false),
    [confirmation, setConfirmation] = useState<any>(null),
    [confirmedFacilities, setConfirmedFacilities] = useState<any[]>([]),
    [reviewBusy, setReviewBusy] = useState(false),
    [queue, setQueue] = useState<any[] | null>(null);
  const [compareData, setCompareData] = useState<any[] | null>(null),
    [blindTest, setBlindTest] = useState<any | null>(null),
    [blindBusy, setBlindBusy] = useState(false),
    [blindWithhold, setBlindWithhold] = useState(10);
  const [scene, setScene] = useState(-1),
    [auto, setAuto] = useState(false),
    [query, setQuery] = useState(""),
    [tasks, setTasks] = useState<Task[]>([]),
    [notes, setNotes] = useState(""),
    [taskStatus, setTaskStatus] = useState("needs_review"),
    [taskBusy, setTaskBusy] = useState(false),
    [toast, setToast] = useState("");
  const toastTimer = useRef<number | null>(null),
    panelScroll = useRef<HTMLDivElement>(null);
  const activeRegion = useRef<string | null>(null);
  activeRegion.current = region?.id ?? null;
  const synthetic = region?.data_mode === "synthetic";
  const notice = (message: string) => {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 5000);
  };
  useEffect(() => {
    api<{ regions: Region[] }>("/regions")
      .then((data) => {
        setRegions(data.regions);
        setRegion(data.regions[0] ?? null);
        if (!data.regions.length)
          throw new Error(
            "No processed regions available. Run make prepare-demo.",
          );
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);
  useEffect(() => {
    if (!region) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setLayers(null);
    setSettlements([]);
    setSelected(null);
    setRevealed(false);
    setSimulation(null);
    setManifest(null);
    setSummary({});
    Promise.all([
      api<any>(`/regions/${region.id}/overview`),
      api<Layers>(`/regions/${region.id}/layers`),
      api<{ settlements: Settlement[] }>(`/regions/${region.id}/settlements`),
    ])
      .then(([overview, l, data]) => {
        if (cancelled) return;
        setSummary(overview.summary);
        setManifest(overview.manifest ?? overview.sources);
        setLayers(l);
        setSettlements(data.settlements);
        setYear(Math.max(...region.years));
        setRevealed(false);
        setSelected(null);
        setSimulation(null);
        setScene(-1);
        setAuto(false);
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [region?.id]);
  const select = async (id: string) => {
    const local = settlements.find((s) => s.id === id);
    if (local) {
      setSelected(local);
      setPanel("evidence");
    }
    try {
      const detail = await api<Settlement>(`/settlements/${id}`);
      setSelected((current) => (current?.id === id ? detail : current));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const reveal = () => {
    setRevealed(true);
    if (settlements.length) {
      select(settlements[0].id);
    }
    setYear(Math.max(...(region?.years ?? [2023])));
  };
  const simulate = async (
    fixedLocation?: [number, number],
    targetId?: string,
  ) => {
    if (!region || busy) return;
    const requestRegion = region.id;
    setBusy(true);
    setError("");
    try {
      const result = await api<Simulation>("/outreach/simulate", {
        method: "POST",
        body: JSON.stringify({
          region_id: region.id,
          target_settlement_ids: targetAll
            ? []
            : targetId
              ? [targetId]
              : selected
                ? [selected.id]
                : [],
          coverage_minutes: threshold,
          locations: fixedLocation ? 1 : locations,
          walking_speed_kmh: speed,
          ...(fixedLocation ? { fixed_location: fixedLocation } : {}),
        }),
      });
      if (activeRegion.current !== requestRegion) return;
      setSimulation(result);
      setRevealed(true);
      notice(
        fixedLocation
          ? "Alternative stop evaluated on the walking network."
          : result.locations.length
            ? "Hypothetical outreach scenario calculated. Drag the purple stop to compare another location."
            : "No stop improves this target’s coverage at the current threshold. Try another candidate or change assumptions.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const enterScene = (index: number) => {
    setScene(index);
    if (index === 0) {
      setRevealed(false);
      setSimulation(null);
      setSelected(null);
      setPanel("candidates");
      setReset((v) => v + 1);
    }
    if (index === 1) {
      setRevealed(true);
      setPanel("candidates");
      setYear(Math.min(...(region?.years ?? [2016])));
    }
    if (index === 2) {
      reveal();
    }
    if (index === 3) {
      reveal();
      simulate(undefined, settlements[0]?.id);
    }
  };
  useEffect(() => {
    if (!auto || scene < 0) return;
    const timer = window.setTimeout(() => {
      if (scene < 3) enterScene(scene + 1);
      else setAuto(false);
    }, 25000);
    return () => window.clearTimeout(timer);
  }, [auto, scene]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).matches("input,textarea,select")) return;
      if (e.key === "Escape") {
        setModal(null);
        setLayerMenu(false);
        setRegionMenu(false);
      }
      if (scene >= 0 && e.key === "ArrowRight") {
        setAuto(false);
        enterScene(Math.min(3, scene + 1));
      }
      if (scene >= 0 && e.key === "ArrowLeft") {
        setAuto(false);
        enterScene(Math.max(0, scene - 1));
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [scene, region, selected, threshold, speed, busy, settlements]);
  useEffect(() => {
    if (modal === "compare" && !compareData)
      api<{ regions: any[] }>("/regions/compare")
        .then((r) => setCompareData(r.regions))
        .catch((e) => setError(e.message));
    if (modal === "tasks")
      api<{ tasks: Task[] }>("/verification-tasks")
        .then((r) => setTasks(r.tasks))
        .catch((e) => setError(e.message));
    if (modal === "tasks" && region && !queue)
      api<{ queue: any[] }>(`/regions/${region.id}/review-queue?limit=8`)
        .then((r) => setQueue(r.queue))
        .catch(() => setQueue([]));
  }, [modal]);
  useEffect(() => {
    panelScroll.current?.scrollTo({ top: 0, behavior: "instant" });
  }, [selected?.id, simulation]);
  const createTask = async () => {
    if (!selected || !region) return;
    setTaskBusy(true);
    try {
      await api("/verification-tasks", {
        method: "POST",
        body: JSON.stringify({
          region_id: region.id,
          settlement_id: selected.id,
          notes,
          status: taskStatus,
          ...(simulation?.locations[0]
            ? { outreach_location: simulation.locations[0] }
            : {}),
        }),
      });
      setModal(null);
      setNotes("");
      notice("Investigation task saved locally with source evidence.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTaskBusy(false);
    }
  };
  const updateTask = async (task: Task, changes: Partial<Task>) => {
    try {
      const result = await api<Task>(`/verification-tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
      setTasks((t) => t.map((x) => (x.id === task.id ? result : x)));
      notice("Investigation updated.");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const submitReview = async (label: string, notes: string) => {
    if (!selected || !region || reviewBusy) return;
    setReviewBusy(true);
    try {
      const result = await api<{ settlement: Settlement }>(
        `/settlements/${selected.id}/reviews`,
        {
          method: "POST",
          body: JSON.stringify({ region_id: region.id, label, notes }),
        },
      );
      setSelected(result.settlement);
      notice(
        label === "non_residential"
          ? "Review saved: population weight removed and regional priorities recomputed."
          : label === "residential"
            ? "Review saved: candidate marked likely residential."
            : "Review saved: this candidate stays high in the review queue.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setReviewBusy(false);
    }
  };
  const pickClinic = async (point: [number, number]) => {
    if (!region || !pickMode) return;
    setPickMode(false);
    setBusy(true);
    try {
      const result = await api<any>(`/regions/${region.id}/confirmed-facilities`, {
        method: "POST",
        body: JSON.stringify({
          region_id: region.id,
          name: `Confirmed clinic ${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`,
          coordinates: point,
        }),
      });
      setConfirmation(result);
      setConfirmedFacilities(result.facilities ?? []);
      const shortened = (result.improved_access ?? []).length;
      notice(
        shortened
          ? `Clinic confirmed locally: ${shortened} candidate${shortened === 1 ? "" : "s"} now reach recorded care faster. Rankings recomputed.`
          : "Clinic confirmed locally; rankings recomputed over the walking network.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const restore = () => {
    setRevealed(false);
    setSelected(null);
    setPanel("candidates");
    setSimulation(null);
    setConfirmation(null);
    setScene(-1);
    setAuto(false);
    setReset((v) => v + 1);
  };
  const filtered = settlements.filter((s) =>
    `${s.display_name} ${s.id}`.toLowerCase().includes(query.toLowerCase()),
  );
  const highest = settlements.filter(
    (s) => (s.priority_score ?? 0) >= 65,
  ).length;
  return (
    <div className="app-shell">
      <header className="header">
        <a className="brand" href="/" aria-label="The Missing Millions home">
          <div className="brand-mark">
            <Globe2 size={26} />
            <i />
          </div>
          <div>
            THE MISSING
            <br />
            <b>MILLIONS</b>
          </div>
        </a>
        <div className="header-separator" />
        <span className="product-label">GEOGRAPHIC INTELLIGENCE</span>
        <div className="header-right">
          <div className="region-picker">
            <button
              className="region-button"
              onClick={() => setRegionMenu(!regionMenu)}
            >
              <MapPin size={14} />
              <span>{region?.name ?? "Loading region"}</span>
              <ChevronDown size={13} />
            </button>
            {regionMenu && (
              <div className="dropdown region-dropdown">
                {regions.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => {
                      setRegion(r);
                      setRegionMenu(false);
                    }}
                  >
                    <MapPin size={14} />
                    <span>
                      {r.name}
                      <small>
                        {r.country} · {r.data_mode} data
                      </small>
                    </span>
                    {r.id === region?.id && <Check size={13} />}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button
            className={`data-mode ${synthetic ? "synthetic" : "real"}`}
            onClick={() => setModal("data")}
          >
            <span />
            {synthetic
              ? "SYNTHETIC DEMONSTRATION"
              : region
                ? "REAL DATA PACKAGE"
                : "DATA STATUS"}
          </button>
          <button
            className="compare-button"
            onClick={() => setModal("compare")}
            title="Compare the prepared regions side by side"
          >
            <GitCompare size={13} /> Compare
          </button>
          <button
            className="discovery-button"
            onClick={() => {
              enterScene(0);
              setAuto(true);
            }}
          >
            <Play size={13} fill="currentColor" /> Start discovery
          </button>
        </div>
      </header>
      <div className="workspace">
        <nav className="rail" aria-label="Application navigation">
          <button
            className={modal === null ? "active" : ""}
            aria-label="Explore map"
            title="Explore map"
            onClick={() => setModal(null)}
          >
            <Globe2 size={21} />
          </button>
          <button
            className={modal === "method" ? "active" : ""}
            aria-label="How the AI works"
            title="How the AI works"
            onClick={() => setModal("method")}
          >
            <Satellite size={21} />
          </button>
          <button
            className={modal === "tasks" ? "active" : ""}
            aria-label="Investigation tasks"
            title="Investigation tasks"
            onClick={() => setModal("tasks")}
          >
            <ClipboardList size={21} />
          </button>
          <div className="rail-bottom">
            <button
              className={modal === "settings" ? "active" : ""}
              aria-label="Simulation settings"
              title="Simulation settings"
              onClick={() => setModal("settings")}
            >
              <SlidersHorizontal size={20} />
            </button>
            <button
              aria-label="About the data"
              title="About the data"
              onClick={() => setModal("data")}
            >
              <Info size={20} />
            </button>
            <span className="rail-status" title="Local analysis package" />
          </div>
        </nav>
        <main className={`map-workspace ${revealed ? "revealed" : ""}`}>
          {loading && (
            <div className="loading-screen">
              <div className="loading-orbit">
                <Satellite size={26} />
              </div>
              <span>Preparing the geographic evidence</span>
              <small>
                Loading precomputed analysis · no live raster processing
              </small>
            </div>
          )}
          {region && layers && (
            <GeoMap
              region={region}
              layers={layers}
              settlements={settlements}
              selected={selected}
              revealed={revealed}
              year={year}
              simulation={simulation}
              showRoads={showRoads}
              showCells={showCells}
              showFacilities={showFacilities}
              showRegistry={showRegistry}
              showSatellite={showSatellite}
              pickMode={pickMode}
              confirmedFacilities={confirmedFacilities}
              onSelect={select}
              reset={reset}
              stage={scene}
              onMoveOutreach={(point) => simulate(point)}
              onPickPoint={pickClinic}
            />
          )}
          <div className="map-topline">
            <span>
              <i /> {synthetic ? "ILLUSTRATIVE STUDY AREA" : "ANALYSIS REGION"}{" "}
              <b>{region?.country ?? "UGANDA"}</b>
            </span>
            <button
              className={pickMode ? "active" : ""}
              onClick={() => {
                setPickMode(!pickMode);
                if (!pickMode)
                  notice(
                    "Click the map to confirm a newly recorded clinic. Walking times and rankings recompute immediately.",
                  );
              }}
              title="Add a locally confirmed clinic and recompute access"
            >
              <MapPin size={15} /> {pickMode ? "Click the map…" : "Confirm new clinic"}
            </button>
            <button
              className={layerMenu ? "active" : ""}
              onClick={() => setLayerMenu(!layerMenu)}
            >
              <Layers3 size={15} /> Map layers <ChevronDown size={12} />
            </button>
          </div>
          {layerMenu && (
            <div className="layer-menu">
              <strong>Visible evidence</strong>
              {[
                [
                  showFacilities,
                  setShowFacilities,
                  "Healthcare facilities",
                  "blue",
                ],
                [showSatellite, setShowSatellite, "Satellite imagery", "white"],
                [showRegistry, setShowRegistry, "Recorded settlements (registry)", "cyan"],
                [showRoads, setShowRoads, "Walking network", "grey"],
                [
                  showCells,
                  setShowCells,
                  "Building-count analysis cells",
                  "teal",
                ],
              ].map(([value, setValue, label, color]: any) => (
                <label key={label}>
                  <input
                    type="checkbox"
                    checked={value}
                    onChange={(e) => setValue(e.target.checked)}
                  />
                  <i className={color} />
                  {label}
                </label>
              ))}
              <p>Local layers remain available offline.</p>
            </div>
          )}
          <div className={`map-story ${revealed ? "compact" : ""}`}>
            <div className="eyebrow">
              <span className="tiny-dot" /> THE MISSING MILLIONS PROJECT
            </div>
            <h1>
              {simulation ? (
                simulation.summary.incremental_covered_population > 0 ? <>
                  Care, a little
                  <br />
                  closer.
                </> : <>No added<br />coverage.</>
              ) : revealed ? (
                <>
                  A signal worth
                  <br />
                  looking into.
                </>
              ) : (
                <>
                  Look beyond
                  <br />
                  what’s mapped<span>.</span>
                </>
              )}
            </h1>
            <p>
              {simulation
                ? simulation.summary.incremental_covered_population > 0
                  ? "Turn geographic evidence into a question for local partners."
                  : "This scenario adds no coverage at the current planning threshold. That is a useful result, too."
                : revealed
                  ? "Not a conclusion. A place to begin a better conversation."
                  : "What if the people missing from our maps are the people who need us most?"}
            </p>
            {!revealed ? (
              <button
                className="reveal-button"
                onClick={reveal}
                disabled={!settlements.length}
              >
                <Satellite size={17} /> Reveal the overlooked{" "}
                <ArrowUpRight size={17} />
              </button>
            ) : (
              <div className="revealed-label">
                <span />
                {simulation
                  ? "OUTREACH SCENARIO ACTIVE"
                  : "SETTLEMENT SIGNAL REVEALED"}
              </div>
            )}
            <button className="story-link" onClick={() => setModal("method")}>
              Explore the methodology <ArrowRight size={13} />
            </button>
          </div>
          {scene >= 0 && (
            <div className="scene-card">
              <div className="scene-top">
                <span>DISCOVERY · 0{scene + 1} / 04</span>
                <button
                  title="Close discovery"
                  aria-label="Close discovery"
                  onClick={() => {
                    setScene(-1);
                    setAuto(false);
                  }}
                >
                  <X size={13} />
                </button>
              </div>
              <h3>{scenes[scene].title}</h3>
              <p>{scenes[scene].text}</p>
              <div className="scene-controls">
                <button
                  onClick={() => {
                    setAuto(false);
                    enterScene(Math.max(0, scene - 1));
                  }}
                  disabled={scene === 0}
                  aria-label="Previous scene"
                >
                  <ArrowLeft size={15} />
                </button>
                <div className="scene-dots">
                  {scenes.map((_, i) => (
                    <button
                      key={i}
                      className={i === scene ? "active" : ""}
                      onClick={() => {
                        setAuto(false);
                        enterScene(i);
                      }}
                      aria-label={`Scene ${i + 1}`}
                    />
                  ))}
                </div>
                <button
                  aria-label={auto ? "Pause discovery" : "Play discovery"}
                  onClick={() => setAuto(!auto)}
                >
                  {auto ? <Pause size={14} /> : <Play size={14} />}
                </button>
                <button
                  onClick={() => {
                    setAuto(false);
                    enterScene(Math.min(3, scene + 1));
                  }}
                  disabled={scene === 3}
                  aria-label="Next scene"
                >
                  <ArrowRight size={15} />
                </button>
              </div>
            </div>
          )}
          <div className="map-attribution">
            {showSatellite && <span>Imagery © Esri, Maxar, Earthstar Geographics</span>}
            {showSatellite && " · "}
            {!synthetic && (
              <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
                © OpenStreetMap contributors (ODbL)
              </a>
            )}
          </div>
          <div className="map-legend">
            <span>
              <i className="blue" />
              {synthetic ? "Fixture" : "Mapped"} healthcare
            </span>
            <span>
              <i className="cyan" />
              Recorded settlements
            </span>
            {revealed && (
              <>
                <span>
                  <i className="teal" />
                  Building signal
                </span>
                <span>
                  <i className="amber" />
                  Investigation candidate
                </span>
              </>
            )}
            {simulation && (
              <span>
                <i className="purple" />
                Hypothetical outreach
              </span>
            )}
            {confirmedFacilities.length > 0 && (
              <span>
                <i className="green" /> Confirmed clinic
              </span>
            )}
          </div>
          {confirmation && (
            <div className="map-summary confirmation-summary">
              <div className="summary-icon">
                <MapPin size={19} />
              </div>
              <div>
                <span>ACCESS RECOMPUTED AFTER CONFIRMED EVIDENCE</span>
                <strong>
                  {number(confirmation.changed_settlements)} <small>rankings updated</small>
                </strong>
                <p>
                  {number(confirmation.improved_access?.length ?? 0)} candidates reach recorded care
                  sooner · {confirmedFacilities.length} confirmed record
                  {confirmedFacilities.length === 1 ? "" : "s"}
                </p>
              </div>
              <button
                onClick={() => setConfirmation(null)}
                aria-label="Close confirmation summary"
              >
                <X size={16} />
              </button>
            </div>
          )}
          {simulation ? (
            <div className="map-summary simulation-summary">
              <div className="summary-icon">
                <Plus size={19} />
              </div>
              <div>
                <span>HYPOTHETICAL INCREMENTAL COVERAGE</span>
                <strong>
                  {number(simulation.summary.incremental_covered_population)}{" "}
                  <small>estimated people</small>
                </strong>
                <p>
                  Within {threshold} min of a service point ·{" "}
                  {synthetic
                    ? "synthetic scenario"
                    : "representative-point estimate"}
                </p>
              </div>
              <button
                onClick={() => setSimulation(null)}
                aria-label="Close outreach simulation"
              >
                <X size={16} />
              </button>
            </div>
          ) : (
            <div className="map-summary">
              <div>
                <span>
                  {revealed ? "CANDIDATE REGIONS" : "ANALYSIS PACKAGE"}
                </span>
                <strong>
                  {revealed
                    ? number(settlements.length)
                    : "Look. Question. Verify."}
                </strong>
                <p>
                  {revealed
                    ? "Settlement-scale signals for investigation"
                    : "Evidence before assumptions."}
                </p>
              </div>
              {revealed && (
                <>
                  <div className="summary-rule" />
                  <div>
                    <span>HIGHER PRIORITY</span>
                    <strong className="amber-text">{number(highest)}</strong>
                    <p>Relative to this region</p>
                  </div>
                </>
              )}
            </div>
          )}
          <div className="timeline">
            <div className="timeline-label">
              <Activity size={17} />
              <span>
                SETTLEMENT
                <br />
                <strong>GROWTH SIGNAL</strong>
              </span>
            </div>
            <div className="timeline-track">
              <div className="timeline-years">
                {(region?.years ?? [2016, 2023]).map((y) => (
                  <button
                    key={y}
                    className={y === year ? "active" : ""}
                    onClick={() => {
                      setYear(y);
                      setRevealed(true);
                    }}
                  >
                    {y}
                  </button>
                ))}
              </div>
              <input
                aria-label="Historical year"
                type="range"
                min={0}
                max={Math.max(0, (region?.years.length ?? 2) - 1)}
                step={1}
                value={Math.max(0, region?.years.indexOf(year) ?? 1)}
                onChange={(e) => {
                  setYear(region?.years[Number(e.target.value)] ?? 2023);
                  setRevealed(true);
                }}
              />
              <div className="timeline-caption">
                {synthetic
                  ? "Synthetic annual observations"
                  : "Available satellite model observations"}
                <span>Historical data · not a live detection</span>
              </div>
            </div>
            <button
              className="reset-button"
              onClick={restore}
              title="Reset to original map"
              aria-label="Reset to original map"
            >
              <RotateCcw size={16} />
              <span>Reset view</span>
            </button>
          </div>
        </main>
        <aside className="evidence-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">FROM SIGNAL TO ACTION</span>
              <h2>
                Investigation desk
                <span>
                  {" "}
                  /{" "}
                  {revealed ? String(settlements.length).padStart(2, "0") : "—"}
                </span>
              </h2>
            </div>
            <button
              title="About this analysis"
              onClick={() => setModal("data")}
            >
              <Info size={16} />
            </button>
          </div>
          <div className="panel-tabs">
            <button
              className={panel === "candidates" ? "active" : ""}
              onClick={() => setPanel("candidates")}
            >
              Candidates <span>{revealed ? settlements.length : "—"}</span>
            </button>
            <button
              className={panel === "evidence" ? "active" : ""}
              disabled={!selected}
              onClick={() => setPanel("evidence")}
            >
              Evidence <ArrowUpRight size={13} />
            </button>
          </div>
          <div className="panel-scroll" ref={panelScroll}>
            {!revealed ? (
              <div className="empty-desk">
                <div className="desk-orbit">
                  <ScanIcon />
                </div>
                <div className="eyebrow">A DIFFERENT STARTING POINT</div>
                <h3>
                  Every community
                  <br />
                  deserves to be seen.
                </h3>
                <p>
                  Existing records tell part of the story. Combine satellite
                  building signals, population estimates and walking networks to
                  find places worth a closer look.
                </p>
                <div className="desk-steps">
                  <span>
                    <Satellite size={17} /> See the settlement signal
                  </span>
                  <span>
                    <Route size={17} /> Understand mapped access
                  </span>
                  <span>
                    <Users size={17} /> Investigate with local partners
                  </span>
                </div>
                <button
                  className="text-link"
                  onClick={() => setModal("method")}
                >
                  How the AI works <ArrowUpRight size={14} />
                </button>
                <div className="source-note">
                  <span className="tiny-dot" />
                  {synthetic
                    ? "Synthetic demonstration data"
                    : "Precomputed source package"}
                  <small>
                    {synthetic
                      ? "No real-world findings are claimed."
                      : "Historical model outputs require field verification."}
                  </small>
                </div>
              </div>
            ) : panel === "evidence" && selected ? (
              <Evidence
                s={selected}
                synthetic={synthetic}
                simulation={simulation}
                onSimulate={() => simulate()}
                onTask={() => {
                  setTaskStatus("needs_review");
                  setModal("create");
                }}
                onMethod={() => setModal("method")}
                busy={busy}
                reviewBusy={reviewBusy}
                onReview={submitReview}
                regionNamer={{ regionName: region?.name, country: region?.country }}
              />
            ) : (
              <div className="candidate-list">
                <div className="list-intro">
                  <p>A closer look starts here.</p>
                  <span>Ranked for investigation, not medical need.</span>
                </div>
                <label className="search-box">
                  <Search size={14} />
                  <input
                    placeholder="Find a candidate…"
                    aria-label="Search candidates"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                {filtered.map((s, i) => (
                  <button
                    key={s.id}
                    className={`candidate-card ${s.id === selected?.id ? "selected" : ""}`}
                    onClick={() => select(s.id)}
                  >
                    <div className="candidate-rank">
                      {String(i + 1).padStart(2, "0")}
                    </div>
                    <div className="candidate-info">
                      <h3>{s.display_name}</h3>
                      <span>
                        <Users size={11} />
                        {number(s.population_estimate)} <b>·</b>
                        <Footprints size={11} />
                        {minutes(s.walking_time_minutes)}
                      </span>
                      <small>
                        {s.building_growth_percentage == null
                          ? "Growth baseline uncertain"
                          : `${s.building_growth_percentage >= 0 ? "+" : ""}${number(s.building_growth_percentage)}% building signal since ${Math.min(...(region?.years ?? [2016]))}`}
                      </small>
                    </div>
                    <div
                      className={`candidate-score ${(s.priority_score ?? 0) >= 65 ? "high" : ""}`}
                    >
                      {number(s.priority_score)}
                      <ArrowUpRight size={12} />
                    </div>
                  </button>
                ))}
                {!filtered.length && (
                  <p className="no-results">No matching candidates.</p>
                )}
                <div className="list-disclaimer">
                  <Info size={14} />
                  <p>
                    Scores reflect selected planning assumptions. Buildings do
                    not establish occupancy; unmapped does not mean unserved.
                  </p>
                </div>
              </div>
            )}
          </div>
          <div className="panel-footer">
            <span className="tiny-dot" />
            <span>LOCAL ANALYSIS · HUMAN VERIFICATION REQUIRED</span>
          </div>
        </aside>
      </div>
      <footer className="statusbar">
        <span>THE FIRST STEP TO SERVING EVERYONE IS SEEING EVERYONE.</span>
        <button onClick={() => setModal("data")}>
          <span className="status-dot" />
          {synthetic
            ? "SYNTHETIC DATA · ALGORITHMS RUN LOCALLY"
            : "PRECOMPUTED GEOGRAPHIC EVIDENCE"}
          <ArrowUpRight size={11} />
        </button>
        <span>PROOF OF CONCEPT / 01</span>
      </footer>
      {error && (
        <div className="error-toast" role="alert">
          <Info size={16} />
          <span>{error}</span>
          <button onClick={() => setError("")} aria-label="Dismiss error">
            <X size={15} />
          </button>
        </div>
      )}
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={17} />
          {toast}
        </div>
      )}
      {modal && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setModal(null);
          }}
        >
          <section
            className={`modal ${modal === "method" ? "method-modal" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-label={
              modal === "method"
                ? "How the AI works"
                : modal === "data"
                  ? "About the data"
                  : modal === "tasks"
                    ? "Investigation tasks"
                    : modal === "settings"
                      ? "Simulation settings"
                      : modal === "compare"
                        ? "Region comparison"
                        : "Create investigation task"
            }
          >
            <button
              className="modal-close"
              aria-label="Close dialog"
              onClick={() => setModal(null)}
            >
              <X size={20} />
            </button>
            {modal === "method" && layers && (
              <Methodology
                s={selected ?? settlements[0] ?? null}
                layers={layers}
                synthetic={synthetic}
              />
            )}
            {modal === "compare" && (
              <>
                <div className="modal-kicker">SAME PIPELINE · DIFFERENT TRUTHS</div>
                <h2>Compare the prepared regions.</h2>
                <p className="modal-lead">
                  Independently acquired samples, compared only through their own
                  aggregates — no records are mixed.
                </p>
                {compareData?.length ? (
                  <div className="compare-grid">
                    <div className="compare-row compare-head">
                      <span>Region</span><span>Candidates</span><span>Median walk</span>
                      <span>Gap mix</span><span>Registry</span>
                    </div>
                    {compareData.map((row: any) => (
                      <div className="compare-row" key={row.region_id}>
                        <span>
                          <strong>{row.name}</strong>
                          <small>{row.country} · {row.data_mode} data</small>
                        </span>
                        <span>{number(row.candidate_count)}<br /><small>{number(row.population_estimate)} est. people</small></span>
                        <span>
                          {row.median_walk_minutes == null ? "Unknown" : `${number(row.median_walk_minutes)} min`}
                          <br /><small>{row.routable_count} routable</small>
                        </span>
                        <span>
                          {Object.entries(row.gap_counts as Record<string, number>).map(([gap, count]) => (
                            <em key={gap} className={`gap-mini gap-${gap}`}>{gap.replaceAll("_", " ")} {count}</em>
                          ))}
                        </span>
                        <span>
                          {number(row.registry_record_count)} records
                          <br />
                          <small>
                            {row.registry_recall == null
                              ? "recall not computed"
                              : `recall ${number(row.registry_recall * 100, 1)}% of ${number(row.registry_recall_points)}`}
                          </small>
                        </span>
                      </div>
                    ))}
                    <p className="chart-note">Median walk uses routable representative points at 4.2 km/h. Registry recall is a geometric coverage claim about an unverified reference layer — nothing more.</p>
                  </div>
                ) : (
                  <p className="chart-note">Preparing regional aggregates…</p>
                )}
              </>
            )}
            {modal === "data" && (
              <>
                <div className="modal-kicker">PROVENANCE & LIMITATIONS</div>
                <h2>Know what you’re looking at.</h2>
                <p className="modal-lead">
                  Every signal has a source. Every estimate has limits.
                </p>
                <div className={`data-banner ${synthetic ? "synthetic" : ""}`}>
                  <Info size={20} />
                  <div>
                    <strong>
                      {synthetic
                        ? "Synthetic demonstration data"
                        : "Real source analysis package"}
                    </strong>
                    <p>
                      {synthetic
                        ? "The current showcase contains generated buildings, population, roads and facilities. The ML and network algorithms run on these inputs. This is not a real discovery about Uganda."
                        : "This package contains source-derived estimates. Consult the manifest for each dataset’s vintage, coverage and processing."}
                    </p>
                  </div>
                </div>
                <div className="data-sources">
                  <SourceRow
                    icon={Satellite}
                    name="Open Buildings 2.5D Temporal"
                    description="Google Research · fractional building counts · 2016–2023"
                    state={
                      synthetic
                        ? "Adapter ready · not used in fixture"
                        : "See source manifest"
                    }
                    url="https://sites.research.google/gr/open-buildings/temporal"
                  />
                  <SourceRow
                    icon={Users}
                    name="WorldPop"
                    description="Modelled population counts · source vintage preserved"
                    state={
                      synthetic
                        ? "Adapter ready · not used in fixture"
                        : "See source manifest"
                    }
                    url="https://hub.worldpop.org/"
                  />
                  <SourceRow
                    icon={Route}
                    name="OpenStreetMap"
                    description="Walking network and general healthcare facility records"
                    state={
                      synthetic
                        ? "Adapter ready · not used in fixture"
                        : "See source manifest"
                    }
                    url="https://www.openstreetmap.org/copyright"
                  />
                </div>
                <div className="source-principles">
                  <p>
                    Building presence does not prove occupancy. Population
                    estimates are modelled. Facility records may be incomplete,
                    and a recorded clinic may not provide every service.
                  </p>
                  <p>
                    Walking times depend on mapped connectivity and speed
                    assumptions. A proposed outreach stop requires local
                    assessment, community participation and authorisation.
                  </p>
                </div>
                <button
                  className="secondary-button"
                  onClick={async () => {
                    try {
                      const data = await api(`/regions/${region?.id}/manifest`);
                      download("data-manifest.json", data);
                    } catch {
                      download(
                        "data-manifest.json",
                        manifest ?? { region, summary },
                      );
                    }
                  }}
                >
                  <Download size={15} /> Download data manifest
                </button>
                <div className="blind-test">
                  <div className="section-title">
                    <strong>Show the work: blind rediscovery test</strong>
                  </div>
                  <p className="modal-lead" style={{ fontSize: 12 }}>
                    Withhold some recorded settlements from the registry, then
                    check whether the satellite pipeline still covers them. The
                    omissions are disclosed evaluation artifacts.
                  </p>
                  <div className="blind-controls">
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={blindWithhold}
                      aria-label="Number of settlements to withhold"
                      onChange={(e) =>
                        setBlindWithhold(
                          Math.max(1, Math.min(200, Number(e.target.value) || 10)),
                        )
                      }
                    />
                    <button
                      className="secondary-button"
                      disabled={blindBusy}
                      onClick={async () => {
                        if (!region) return;
                        setBlindBusy(true);
                        try {
                          const data = await api<any>(
                            `/regions/${region.id}/blind-test?withhold=${blindWithhold}`,
                          );
                          setBlindTest(data);
                        } catch (e) {
                          setError((e as Error).message);
                        } finally {
                          setBlindBusy(false);
                        }
                      }}
                    >
                      {blindBusy ? (
                        <LoaderCircle className="spin" size={15} />
                      ) : (
                        <FlaskConical size={15} />
                      )}{" "}
                      Run blind test
                    </button>
                  </div>
                  {blindTest && (
                    <div className="blind-result">
                      <strong>
                        {blindTest.status === "available"
                          ? `${blindTest.recovered} of ${blindTest.withheld_count} withheld records still inside detection coverage (${number((blindTest.recall ?? 0) * 100, 1)}%)`
                          : blindTest.note || blindTest.reason || blindTest.status}
                      </strong>
                      {blindTest.status === "available" && (
                        <p>
                          “{blindTest.disclosure}” Radius {number(blindTest.radius_m)} m.
                        </p>
                      )}
                    </div>
                  )}
                </div>
                <details className="manifest">
                  <summary>Inspect machine-readable provenance</summary>
                  <pre>
                    {JSON.stringify(manifest ?? { region, summary }, null, 2)}
                  </pre>
                </details>
              </>
            )}
            {modal === "settings" && (
              <>
                <div className="modal-kicker">TEST THE ASSUMPTIONS</div>
                <h2>Explore another scenario.</h2>
                <p className="modal-lead">
                  Planning choices affect the result. Keep them visible.
                </p>
                <label className="field-label">
                  Walking coverage threshold{" "}
                  <strong>{threshold} minutes</strong>
                  <input
                    type="range"
                    min={10}
                    max={120}
                    step={5}
                    value={threshold}
                    onChange={(e) => setThreshold(+e.target.value)}
                  />
                </label>
                <label className="field-label">
                  Walking speed <strong>{speed} km/h</strong>
                  <input
                    type="range"
                    min={3}
                    max={5.5}
                    step={0.1}
                    value={speed}
                    onChange={(e) => setSpeed(+e.target.value)}
                  />
                </label>
                <label className="field-label">
                  Hypothetical outreach stops
                  <select
                    value={locations}
                    onChange={(e) => setLocations(+e.target.value)}
                  >
                    <option value={1}>One stop</option>
                    <option value={2}>Two stops</option>
                  </select>
                </label>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={targetAll}
                    onChange={(e) => setTargetAll(e.target.checked)}
                  />
                  Optimise coverage across all candidate settlements
                </label>
                <p className="form-help">
                  When unchecked, the selected candidate is the target. Routes
                  include off-network connections. These are planning bands, not
                  clinical standards.
                </p>
                <button
                  className="primary-button full"
                  disabled={busy || !region}
                  onClick={() => {
                    setModal(null);
                    simulate();
                  }}
                >
                  <ArrowUpRight size={17} /> Recalculate outreach scenario
                </button>
                <div className="modal-disclaimer">
                  <Info size={16} />
                  <span>
                    Road passability, terrain, safety, staffing and local
                    feasibility have not been evaluated.
                  </span>
                </div>
              </>
            )}
            {modal === "create" && selected && (
              <>
                <div className="modal-kicker">
                  FROM INFERENCE TO INVESTIGATION
                </div>
                <h2>A question for the field.</h2>
                <p className="modal-lead">
                  {selected.display_name} · {selected.id}
                </p>
                <div className="task-evidence">
                  <span>
                    <Users size={15} />
                    {number(selected.population_estimate)} estimated population
                  </span>
                  <span>
                    <Footprints size={15} />
                    {minutes(selected.walking_time_minutes)} to mapped
                    healthcare
                  </span>
                  <small>
                    {synthetic
                      ? "Synthetic evidence is included in this demonstration record."
                      : "Source evidence, geometry and uncertainty are saved with the task."}
                  </small>
                </div>
                <label className="field-label">
                  Investigation status
                  <select
                    value={taskStatus}
                    onChange={(e) => setTaskStatus(e.target.value)}
                  >
                    {statusOptions.map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field-label">
                  Notes for local partners
                  <textarea
                    rows={3}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Context, questions, or local knowledge…"
                  />
                </label>
                <div className="verification-questions">
                  <strong>Questions to verify together</strong>
                  <ul>
                    <li>
                      Are homes occupied, and how do residents describe the
                      settlement?
                    </li>
                    <li>
                      Are any healthcare services missing from the available
                      records?
                    </li>
                    <li>
                      Are these roads and paths usable, and what transport is
                      available?
                    </li>
                    <li>Would local communities find outreach useful?</li>
                  </ul>
                </div>
                <button
                  className="primary-button full"
                  onClick={createTask}
                  disabled={taskBusy}
                >
                  {taskBusy ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <ClipboardList size={16} />
                  )}{" "}
                  Save investigation task
                </button>
                <p className="form-help">
                  Saved in local SQLite storage. No information is uploaded to
                  OpenStreetMap.
                </p>
              </>
            )}
            {modal === "tasks" && (
              <>
                <div className="modal-kicker">THE HUMAN PART OF THE LOOP</div>
                <h2>Investigation tasks.</h2>
                <p className="modal-lead">
                  Evidence becomes useful when someone looks closer.
                </p>
                <div className="task-toolbar">
                  <span>
                    {tasks.length} local{" "}
                    {tasks.length === 1 ? "investigation" : "investigations"}
                  </span>
                  <button
                    className="secondary-button"
                    onClick={() => download("investigation-tasks.json", tasks)}
                  >
                    <Download size={14} /> Export JSON
                  </button>
                  <a
                    className="secondary-button"
                    href="/api/verification-tasks/export?format=csv"
                    download
                  >
                    <Download size={14} /> CSV
                  </a>
                </div>
                {queue && queue.length > 0 && (
                  <div className="review-queue">
                    <strong>Where one more observation changes the most</strong>
                    <p className="chart-note">
                      Active-learning queue: priority × unresolved uncertainty,
                      excluding already-reviewed candidates. Not a medical-need
                      score.
                    </p>
                    {queue.map((item: any, index: number) => (
                      <button
                        className="queue-row"
                        key={item.settlement_id}
                        onClick={() => {
                          setModal(null);
                          select(item.settlement_id);
                        }}
                      >
                        <span className="queue-rank">{index + 1}</span>
                        <span className="queue-name">
                          {item.display_name}
                          {item.candidate_gap_type &&
                            item.candidate_gap_type !== "none" && (
                              <em> · {item.candidate_gap_type.replaceAll("_", " ")}</em>
                            )}
                        </span>
                        <span className="queue-value">
                          {number(item.investigation_value, 1)}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {tasks.length ? (
                  tasks.map((task) => (
                    <div className="saved-task" key={task.id}>
                      <div>
                        <strong>
                          {settlements.find((s) => s.id === task.settlement_id)
                            ?.display_name ?? task.settlement_id}
                        </strong>
                        <span>
                          {task.id} ·{" "}
                          {new Date(task.created_at).toLocaleDateString(
                            "en-GB",
                          )}
                        </span>
                      </div>
                      <select
                        aria-label={`Status for ${task.settlement_id}`}
                        value={task.status}
                        onChange={(e) =>
                          updateTask(task, { status: e.target.value })
                        }
                      >
                        {statusOptions.map(([v, l]) => (
                          <option key={v} value={v}>
                            {l}
                          </option>
                        ))}
                      </select>
                      <textarea
                        aria-label={`Notes for ${task.settlement_id}`}
                        defaultValue={task.notes ?? ""}
                        onBlur={(e) => {
                          if (e.target.value !== task.notes)
                            updateTask(task, { notes: e.target.value });
                        }}
                        placeholder="Add field notes…"
                      />
                    </div>
                  ))
                ) : (
                  <div className="tasks-empty">
                    <ClipboardList size={34} />
                    <h3>Start with a place worth investigating.</h3>
                    <p>
                      Reveal the settlement signals, open a candidate and create
                      a task.
                    </p>
                    <button
                      className="primary-button"
                      onClick={() => {
                        setModal(null);
                        reveal();
                      }}
                    >
                      Explore candidates <ArrowRight size={15} />
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
const statusOptions = [
  ["needs_review", "Needs review"],
  ["assigned", "Assigned"],
  ["in_progress", "Field verification in progress"],
  ["verified", "Verified"],
  ["rejected", "Rejected / insufficient evidence"],
];
function ScanIcon() {
  return (
    <>
      <Satellite size={30} />
      <i />
      <b />
    </>
  );
}
function SourceRow({
  icon: Icon,
  name,
  description,
  state,
  url,
}: {
  icon: any;
  name: string;
  description: string;
  state: string;
  url: string;
}) {
  return (
    <div className="source-row">
      <Icon size={22} />
      <div>
        <strong>{name}</strong>
        <p>{description}</p>
        <small>{state}</small>
      </div>
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        aria-label={`${name} source`}
      >
        <ExternalLink size={15} />
      </a>
    </div>
  );
}
