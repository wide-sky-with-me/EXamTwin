import { BookOpenCheck, FileText, GraduationCap, ShieldCheck } from "lucide-react";
import { motion } from "motion/react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { ErrorBanner } from "./components/Feedback";
import { ThemeSwitch } from "./components/ThemeSwitch";
import { apiClient, setApiSubject, unwrapApi } from "./lib/api";
import type { PlatformStatus, ReviewItem } from "./types";

const SubjectManagement = lazy(() =>
  import("./pages/SubjectManagement").then(({ SubjectManagement: Page }) => ({ default: Page })),
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

type Tab = "subjects" | "answering" | "grading" | "reviews";

const navItems = [
  { id: "subjects" as const, label: "科目管理", icon: GraduationCap },
  { id: "answering" as const, label: "试卷作答", icon: FileText },
  { id: "grading" as const, label: "答案评分", icon: BookOpenCheck },
  { id: "reviews" as const, label: "复核队列", icon: ShieldCheck },
];

function initialTab(): Tab {
  const value = window.localStorage.getItem("examtwin.activeTab");
  return navItems.some((item) => item.id === value) ? value as Tab : "subjects";
}

export default function App() {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [platform, setPlatform] = useState<PlatformStatus | null>(null);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshSubjects = useCallback(async () => {
    const next = await unwrapApi(apiClient.GET("/api/v1/subjects/status"));
    setPlatform(next);
  }, []);

  const refreshReviews = useCallback(async () => {
    const next = await unwrapApi(apiClient.GET("/api/v1/grading/reviews/all"));
    setReviews(next);
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([refreshSubjects(), refreshReviews()]);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [refreshReviews, refreshSubjects]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const subjects = useMemo(() => platform?.subjects ?? [], [platform?.subjects]);
  const reviewCount = reviews.length;
  const answeringEnabled = useMemo(
    () => subjects.some((subject) => subject.answering_enabled),
    [subjects],
  );

  function selectTab(nextTab: Tab) {
    setTab(nextTab);
    window.localStorage.setItem("examtwin.activeTab", nextTab);
    if (nextTab === "subjects" || nextTab === "reviews") setApiSubject(null);
  }

  return (
    <div className="app-shell">
        <aside className="app-sidebar">
          <div className="brand-lockup">
            <span>ET</span>
            <strong>ExamTwin</strong>
          </div>
          <nav aria-label="主导航">
            {navItems.map(({ id, label, icon: Icon }) => (
              <motion.button
                aria-current={tab === id ? "page" : undefined}
                className={tab === id ? "active" : ""}
                key={id}
                onClick={() => selectTab(id)}
                type="button"
                whileTap={{ scale: 0.98 }}
              >
                <Icon size={18} />
                <span>{label}</span>
                {id === "reviews" && reviewCount > 0 && <em>{reviewCount}</em>}
              </motion.button>
            ))}
          </nav>
          <div className="sidebar-footer"><ThemeSwitch /></div>
        </aside>

        <main className="app-main">
          <ErrorBanner message={error} />
          <Suspense fallback={<div className="page-loading">正在加载…</div>}>
            <motion.div
              animate={{ opacity: 1, y: 0 }}
              className="app-view"
              initial={{ opacity: 0, y: 8 }}
              key={tab}
              transition={{ duration: 0.22, ease: [0.25, 0.1, 0.25, 1] }}
            >
              {tab === "subjects" && (
                <SubjectManagement loading={loading} refresh={refreshSubjects} subjects={subjects} />
              )}
              {tab === "answering" && (
                <PaperAnswering enabled={answeringEnabled} subjects={subjects} />
              )}
              {tab === "grading" && (
                <Grading onCreated={refreshReviews} subjects={subjects} />
              )}
              {tab === "reviews" && (
                <Reviews items={reviews} refresh={refreshReviews} />
              )}
            </motion.div>
          </Suspense>
        </main>
    </div>
  );
}
