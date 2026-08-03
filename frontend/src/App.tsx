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
import { api } from "./lib/api";
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
  const [connected, setConnected] = useState(false);
  const [paperJobsReady, setPaperJobsReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [health, nextStats, nextPoints, nextRelations, nextReviews] = await Promise.all([
        api<Health>("/health"),
        api<Stats>("/stats"),
        api<KnowledgePoint[]>("/knowledge/points"),
        api<KnowledgeRelation[]>("/knowledge/relations"),
        api<ReviewItem[]>("/grading/reviews"),
      ]);
      setPaperJobsReady(
        Array.isArray(health.capabilities)
          && health.capabilities.includes("paper_jobs_v1")
          && health.capabilities.includes("task_events_v1")
          && health.capabilities.includes("answering_agent_v1"),
      );
      setStats(nextStats); setPoints(nextPoints); setRelations(nextRelations); setReviews(nextReviews);
      setConnected(true); setError(null);
    } catch (cause) {
      setConnected(false);
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
          <p><i className={connected ? "up" : ""} /> PostgreSQL</p>
          <p><i className={connected ? "up" : ""} /> Qdrant</p>
          <small>Docker Compose managed</small>
        </div>
      </aside>
      <main>
        <header>
          <span>{currentLabel}</span>
          <div className={connected && paperJobsReady ? "api-live" : "api-offline"}>
            <i />
            {!connected ? "API offline" : paperJobsReady ? "API connected" : "API outdated"}
          </div>
        </header>
        <div className="content">
          <Suspense fallback={<div className="panel empty">正在加载页面…</div>}>
            {error && tab === "overview" && <ErrorBanner message={`请先启动 Docker 基础设施和 FastAPI：${error}`} />}
            {tab === "overview" && <Overview stats={stats} refresh={refresh} loading={loading} />}
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
