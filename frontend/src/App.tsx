import {
  Archive,
  BookOpenCheck,
  FileText,
  Layers3,
  Network,
  ShieldCheck,
} from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { ErrorBanner } from "./components/Feedback";
import { ThemeSwitch } from "./components/ThemeSwitch";
import {
  apiClient,
  getApiSubject,
  setApiSubject,
  unwrapApi,
} from "./lib/api";
import type {
  Health,
  KnowledgePoint,
  KnowledgeRelation,
  PlatformStatus,
  ReviewItem,
} from "./types";

type Tab = "overview" | "knowledge" | "ask" | "grading" | "reviews";

const navItems: {
  id: Tab;
  label: string;
  icon: typeof Archive;
  capabilities?: string[];
}[] = [
  { id: "overview", label: "状态总览", icon: Archive },
  { id: "ask", label: "试卷作答", icon: FileText, capabilities: ["paper_jobs_v1", "answering_agent_v1"] },
  { id: "knowledge", label: "知识库", icon: Network, capabilities: ["knowledge_graph_v1"] },
  { id: "grading", label: "答案评分", icon: BookOpenCheck, capabilities: ["grading_assessment_v1"] },
  { id: "reviews", label: "复核队列", icon: ShieldCheck, capabilities: ["human_review_v1"] },
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
  const [selectedSubjectId, setSelectedSubjectId] = useState<string | null>(getApiSubject);
  const [platform, setPlatform] = useState<PlatformStatus | null>(null);
  const [points, setPoints] = useState<KnowledgePoint[]>([]);
  const [relations, setRelations] = useState<KnowledgeRelation[]>([]);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const subjects = useMemo(() => platform?.subjects ?? [], [platform]);
  const subject = useMemo(
    () => subjects.find((item) => item.id === selectedSubjectId) ?? null,
    [selectedSubjectId, subjects],
  );

  const selectSubject = useCallback((packageId: string | null) => {
    setApiSubject(packageId);
    setSelectedSubjectId(packageId);
    setPoints([]);
    setRelations([]);
    setReviews([]);
    setError(null);
    if (!packageId) setTab("overview");
  }, []);

  const loadPlatform = useCallback(async () => {
    const [nextHealth, nextPlatform] = await Promise.all([
      unwrapApi(apiClient.GET("/api/v1/health")),
      unwrapApi(apiClient.GET("/api/v1/subjects/status")),
    ]);
    setHealth(nextHealth);
    setPlatform(nextPlatform);
    setConnected(true);
    const selected = getApiSubject();
    if (selected && !nextPlatform.subjects.some((item) => item.id === selected)) {
      selectSubject(null);
    }
  }, [selectSubject]);

  const loadKnowledge = useCallback(async () => {
    const requestedSubject = getApiSubject();
    if (!requestedSubject) return;
    const [nextPoints, nextRelations] = await Promise.all([
      unwrapApi(apiClient.GET("/api/v1/knowledge/points")),
      unwrapApi(apiClient.GET("/api/v1/knowledge/relations")),
    ]);
    if (getApiSubject() !== requestedSubject) return;
    setPoints(nextPoints);
    setRelations(nextRelations);
  }, []);

  const loadReviews = useCallback(async () => {
    const requestedSubject = getApiSubject();
    if (!requestedSubject) return;
    const nextReviews = await unwrapApi(apiClient.GET("/api/v1/grading/reviews"));
    if (getApiSubject() === requestedSubject) setReviews(nextReviews);
  }, []);

  const refreshTab = useCallback(async (target: Tab) => {
    setLoading(true);
    const requests: Promise<unknown>[] = [loadPlatform()];
    if (getApiSubject() && target === "knowledge") requests.push(loadKnowledge());
    if (getApiSubject() && (target === "reviews" || target === "overview")) {
      requests.push(loadReviews());
    }
    try {
      await Promise.all(requests);
      setError(null);
    } catch (cause) {
      setConnected(false);
      setError(cause instanceof Error ? cause.message : "数据刷新失败");
    } finally {
      setLoading(false);
    }
  }, [loadKnowledge, loadPlatform, loadReviews]);

  const refreshReviews = useCallback(async () => {
    try {
      await Promise.all([loadReviews(), loadPlatform()]);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "复核队列刷新失败");
    }
  }, [loadPlatform, loadReviews]);

  useEffect(() => { void refreshTab(tab); }, [refreshTab, selectedSubjectId, tab]);
  useEffect(() => {
    const refreshVisibleData = () => {
      if (document.visibilityState === "visible") void refreshTab(tab);
    };
    window.addEventListener("focus", refreshVisibleData);
    document.addEventListener("visibilitychange", refreshVisibleData);
    return () => {
      window.removeEventListener("focus", refreshVisibleData);
      document.removeEventListener("visibilitychange", refreshVisibleData);
    };
  }, [refreshTab, tab]);

  const availableNavItems = useMemo(() => {
    if (!health || !subject) return navItems.filter((item) => item.id === "overview");
    const capabilities = new Set(health.capabilities);
    return navItems.filter((item) => {
      if (item.id === "ask" && !subject.answering_enabled) return false;
      return item.capabilities?.every((capability) => capabilities.has(capability)) ?? true;
    });
  }, [health, subject]);

  useEffect(() => {
    if (!availableNavItems.some((item) => item.id === tab)) setTab("overview");
  }, [availableNavItems, tab]);

  const currentLabel = navItems.find((item) => item.id === tab)?.label;
  const infrastructure = platform?.infrastructure ?? health?.infrastructure;
  const apiHealthy = connected && health?.status === "ok";
  const paperJobsReady = Boolean(
    subject?.answering_enabled
      && subject.vector_index_ready
      && health?.capabilities.includes("paper_jobs_v1")
      && health.capabilities.includes("task_events_v1")
      && health.capabilities.includes("answering_agent_v1")
      && infrastructure
      && Object.values(infrastructure).every(Boolean),
  );

  return (
    <div className="app-shell">
      <aside>
        <div className="brand">
          <div><Layers3 size={22} /></div>
          <span><b>ExamTwin</b><small>证据驱动的考试助手</small></span>
        </div>
        <nav aria-label="主要功能">
          {availableNavItems.map(({ id, label, icon: Icon }) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
              <Icon size={19} />
              <span>{label}</span>
              {id === "reviews" && reviews.length > 0 && <em>{reviews.length}</em>}
            </button>
          ))}
        </nav>
        <div className="subject-card">
          <label htmlFor="subject-context">科目上下文</label>
          <select
            id="subject-context"
            value={selectedSubjectId ?? ""}
            onChange={(event) => selectSubject(event.target.value || null)}
          >
            <option value="">选择一个科目</option>
            {subjects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.subject_code} · {item.title.replace(/^OxfordAQA International (AS\/A-level )?/, "")}
              </option>
            ))}
          </select>
          {subject ? (
            <>
              <span>{subject.board_name}</span>
              <strong>{subject.subject_code}</strong>
              <p>{subject.title}</p>
              <small className={subject.vector_index_ready ? "subject-ready" : "subject-pending"}>
                {subject.vector_index_ready ? `${subject.vector_points} 个检索节点` : "知识索引未就绪"}
              </small>
            </>
          ) : (
            <p>选择后，资料、知识、答题与评分会一起切换。</p>
          )}
        </div>
      </aside>
      <main>
        <header>
          <div className="header-context">
            <span>{currentLabel}</span>
            <small>{subject ? `${subject.subject_code} · ${subject.board_name}` : "请选择科目上下文"}</small>
          </div>
          <div className="header-actions">
            <ThemeSwitch />
            <div
              className={apiHealthy ? "api-live" : "api-offline"}
              title={infrastructure ? `PostgreSQL ${infrastructure.postgresql ? "正常" : "异常"} · Qdrant ${infrastructure.qdrant ? "正常" : "异常"} · 对象存储 ${infrastructure.object_storage ? "正常" : "异常"}` : undefined}
            >
              <i />
              {!connected ? "服务离线" : !apiHealthy ? "服务降级" : "系统正常"}
            </div>
          </div>
        </header>
        <div className="content">
          <Suspense fallback={<div className="panel empty">正在加载页面…</div>}>
            {error && <ErrorBanner message={`服务暂时不可用或数据刷新失败：${error}`} />}
            {tab === "overview" && (
              <Overview
                platform={platform}
                selected={subject}
                selectSubject={selectSubject}
                refresh={() => refreshTab("overview")}
                loading={loading}
              />
            )}
            {tab === "knowledge" && subject && (
              <Knowledge
                key={subject.id}
                points={points}
                relations={relations}
                subject={subject}
                refresh={() => refreshTab("knowledge")}
              />
            )}
            {tab === "ask" && subject && (
              <PaperAnswering key={subject.id} enabled={paperJobsReady} subject={subject} />
            )}
            {tab === "grading" && subject && (
              <Grading key={subject.id} subject={subject} onCreated={refreshReviews} />
            )}
            {tab === "reviews" && subject && (
              <Reviews key={subject.id} items={reviews} refresh={refreshReviews} />
            )}
          </Suspense>
        </div>
      </main>
    </div>
  );
}
