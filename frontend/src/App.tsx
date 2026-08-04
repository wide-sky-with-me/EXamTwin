import {
  BarChart3,
  BookOpenCheck,
  Boxes,
  FileText,
  Network,
  ShieldCheck,
} from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ErrorBanner } from "./components/Feedback";
import { apiClient, unwrapApi } from "./lib/api";
import type {
  Health,
  KnowledgePoint,
  KnowledgeRelation,
  ReviewItem,
  Stats,
} from "./types";

type Tab = "overview" | "knowledge" | "ask" | "grading" | "reviews";

const navItems: { id: Tab; label: string; icon: typeof BarChart3 }[] = [
  { id: "overview", label: "数据总览", icon: BarChart3 },
  { id: "knowledge", label: "知识难度", icon: Network },
  { id: "ask", label: "试卷逐题作答", icon: FileText },
  { id: "grading", label: "自动评分", icon: BookOpenCheck },
  { id: "reviews", label: "人工复核", icon: ShieldCheck },
];

const Overview = lazy(() =>
  import("./pages/Overview").then(({ Overview: Page }) => ({ default: Page })),
);
const Knowledge = lazy(() =>
  import("./pages/Knowledge").then(({ Knowledge: Page }) => ({ default: Page })),
);
const PaperAnswering = lazy(() =>
  import("./pages/PaperAnswering").then(({ PaperAnswering: Page }) => ({ default: Page })),
);
const Grading = lazy(() =>
  import("./pages/Grading").then(({ Grading: Page }) => ({ default: Page })),
);
const Reviews = lazy(() =>
  import("./pages/Reviews").then(({ Reviews: Page }) => ({ default: Page })),
);

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [stats, setStats] = useState<Stats | null>(null);
  const [points, setPoints] = useState<KnowledgePoint[]>([]);
  const [relations, setRelations] = useState<KnowledgeRelation[]>([]);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [connected, setConnected] = useState(false);
  const [paperJobsReady, setPaperJobsReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextHealth, nextStats, nextPoints, nextRelations, nextReviews] = await Promise.all([
        unwrapApi(apiClient.GET("/api/v1/health")),
        unwrapApi(apiClient.GET("/api/v1/stats")),
        unwrapApi(apiClient.GET("/api/v1/knowledge/points")),
        unwrapApi(apiClient.GET("/api/v1/knowledge/relations")),
        unwrapApi(apiClient.GET("/api/v1/grading/reviews")),
      ]);
      setPaperJobsReady(
        Array.isArray(nextHealth.capabilities)
          && nextHealth.capabilities.includes("paper_jobs_v1")
          && nextHealth.capabilities.includes("task_events_v1")
          && nextHealth.capabilities.includes("answering_agent_v1")
          && nextHealth.infrastructure != null
          && Object.values(nextHealth.infrastructure).every(Boolean),
      );
      setHealth(nextHealth);
      setStats(nextStats); setPoints(nextPoints); setRelations(nextRelations); setReviews(nextReviews);
      setConnected(true); setError(null);
    } catch (cause) {
      setConnected(false);
      setHealth(null);
      setPaperJobsReady(false);
      setError(cause instanceof Error ? cause.message : "后端连接失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const refreshVisibleData = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", refreshVisibleData);
    document.addEventListener("visibilitychange", refreshVisibleData);
    return () => {
      window.removeEventListener("focus", refreshVisibleData);
      document.removeEventListener("visibilitychange", refreshVisibleData);
    };
  }, [refresh]);
  const currentLabel = useMemo(() => navItems.find((item) => item.id === tab)?.label, [tab]);
  const infrastructure = health?.infrastructure;
  const apiHealthy = connected && health?.status === "ok";

  return (
    <div className="app-shell">
      <aside>
        <div className="brand"><div><Boxes size={24} /></div><span><b>ExamTwin</b><small>9660 Evidence Lab</small></span></div>
        <nav>{navItems.map(({ id, label, icon: Icon }) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
            <Icon size={19} /><span>{label}</span>{id === "reviews" && reviews.length > 0 && <em>{reviews.length}</em>}
          </button>
        ))}</nav>
        <div className="infra">
          <span>INFRASTRUCTURE</span>
          <p><i className={infrastructure?.postgresql ? "up" : connected ? "down" : ""} /> PostgreSQL</p>
          <p><i className={infrastructure?.qdrant ? "up" : connected ? "down" : ""} /> Qdrant</p>
          <p><i className={infrastructure?.object_storage ? "up" : connected ? "down" : ""} /> Object storage</p>
          <small>Docker Compose managed</small>
        </div>
      </aside>
      <main>
        <header>
          <span>{currentLabel}</span>
          <div className={apiHealthy && paperJobsReady ? "api-live" : "api-offline"}>
            <i />
            {!connected
              ? "API offline"
              : !apiHealthy
                ? "API degraded"
                : paperJobsReady
                  ? "API connected"
                  : "API outdated"}
          </div>
        </header>
        <div className="content">
          <Suspense fallback={<div className="panel empty">正在加载页面…</div>}>
            {error && <ErrorBanner message={`请先启动 Docker 基础设施和 FastAPI：${error}`} />}
            {tab === "overview" && (
              <Overview
                stats={stats}
                refresh={refresh}
                loading={loading}
                postgresqlUp={infrastructure?.postgresql ?? null}
              />
            )}
            {tab === "knowledge" && <Knowledge points={points} relations={relations} />}
            {tab === "ask" && <PaperAnswering enabled={paperJobsReady} />}
            {tab === "grading" && <Grading onCreated={refresh} />}
            {tab === "reviews" && <Reviews items={reviews} refresh={refresh} />}
          </Suspense>
        </div>
      </main>
    </div>
  );
}
