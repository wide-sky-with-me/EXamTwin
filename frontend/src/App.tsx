import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Breadcrumb,
  Button,
  Flex,
  Layout,
  Menu,
  Result,
  Spin,
  Tooltip,
  Typography,
} from "antd";
import {
  Files,
  GraduationCap,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
} from "lucide-react";
import { lazy, type ReactNode, Suspense, useEffect, useState } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router";

import { ConversionQueueProvider } from "./components/ConversionQueueProvider";
import { ThemeSwitch } from "./components/ThemeSwitch";
import { apiClient, unwrapApi } from "./lib/api";
import {
  PAPER_ROUTE_PATTERNS,
  paperAnsweringPath,
  paperAnswersPath,
  paperDetailPath,
  paperDocumentPath,
  paperGradingPath,
  paperIndexPath,
  parsePaperLocation,
  parseSubjectId,
  subjectPath,
} from "./lib/paper-routes";
import type { PlatformStatus, ReviewItem, SubjectStatus } from "./types";

const SubjectWorkspace = lazy(() => import("./components/SubjectWorkspace").then(({ SubjectWorkspace: Workspace }) => ({ default: Workspace })));
const SubjectOverview = lazy(() => import("./pages/SubjectOverview").then(({ SubjectOverview: Page }) => ({ default: Page })));
const SubjectManagement = lazy(() => import("./pages/SubjectManagement").then(({ SubjectManagement: Page }) => ({ default: Page })));
const PaperManagement = lazy(() => import("./pages/PaperManagement").then(({ PaperManagement: Page }) => ({ default: Page })));
const Reviews = lazy(() => import("./pages/Reviews").then(({ Reviews: Page }) => ({ default: Page })));

const { Content } = Layout;
const { Text, Title } = Typography;

const LAST_SUBJECT_STORAGE_KEY = "examtwin.lastSubjectId";

type AppMenuItem = {
  key: string;
  icon: ReactNode;
  label: ReactNode;
  path: string;
};

export function SidebarNavigation({
  collapsed,
  items,
  onNavigate,
  onToggle,
  selectedKey,
}: {
  collapsed: boolean;
  items: AppMenuItem[];
  onNavigate: (path: string) => void;
  onToggle: () => void;
  selectedKey: string;
}) {
  return (
    <div className={`app-sidebar-inner flex h-full min-h-0 flex-col py-5 ${collapsed ? "px-2" : "px-4"}`}>
      <div className={`app-sidebar-brand mb-6 flex items-center gap-3 px-1 ${collapsed ? "justify-center" : "justify-between"}`}>
        <Button
          aria-label="返回科目列表"
          className="app-brand-button !h-auto !px-2 !py-1.5"
          icon={<span className="app-brand-mark"><img alt="" aria-hidden="true" src="/examtwin-icon.svg" /></span>}
          onClick={() => onNavigate("/subjects")}
          type="text"
        >
          {!collapsed && (
            <span className="flex flex-col items-start leading-tight">
              <Text className="!text-[15px]" strong>ExamTwin</Text>
              <Text className="!text-[10px] !tracking-[0.12em]" type="secondary">ASSESSMENT</Text>
            </span>
          )}
        </Button>
      </div>
      <nav aria-label="主导航" className="min-h-0 flex-1">
        <Menu
          className="app-side-menu"
          inlineCollapsed={collapsed}
          items={items.map(({ key, icon, label }) => ({ key, icon, label }))}
          mode="inline"
          onClick={({ key }) => onNavigate(items.find((item) => item.key === key)?.path ?? "/subjects")}
          selectedKeys={[selectedKey]}
        />
      </nav>
      <div className="app-sidebar-footer mt-5">
        {!collapsed && (
          <div className="rounded-2xl border border-[var(--app-glass-border)] bg-[var(--app-content-glass)] p-2.5 shadow-sm backdrop-blur-xl">
            <Text className="mb-2 block px-1 !text-[10px] !font-semibold !tracking-[0.12em]" type="secondary">外观</Text>
            <ThemeSwitch />
          </div>
        )}
        <Tooltip placement="right" title={collapsed ? "展开侧栏" : "收起侧栏"}>
          <Button
            aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
            block
            className="app-sidebar-toggle"
            icon={collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
            onClick={onToggle}
            type="text"
          >
            {!collapsed && "收起侧栏"}
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}

function subjectOrFirst(subjects: SubjectStatus[], requested?: string) {
  return subjects.find((item) => item.id === requested)?.id ?? subjects[0]?.id ?? "";
}


function SubjectRedirect({ subjects }: { subjects: SubjectStatus[] }) {
  const subjectId = subjectOrFirst(subjects, window.localStorage.getItem(LAST_SUBJECT_STORAGE_KEY) ?? undefined);
  if (!subjectId) return <Navigate replace to="/subjects" />;
  return <Navigate replace to={paperIndexPath(subjectId)} />;
}

function SubjectWorkspaceRoute({ subjects, refresh, view }: { subjects: SubjectStatus[]; refresh: () => Promise<void>; view: "documents" | "knowledge" }) {
  const navigate = useNavigate();
  const { subjectId = "" } = useParams();
  const subject = subjects.find((item) => item.id === subjectId);
  if (!subject) return <Result status="404" title="科目不存在" extra={<Button onClick={() => navigate("/subjects")}>返回科目列表</Button>} />;
  return (
    <div className="subject-overview-page">
      <Breadcrumb items={[{ title: <a onClick={() => navigate("/subjects")}>科目</a> }, { title: <a onClick={() => navigate(subjectPath(subject.id))}>{subject.title}</a> }, { title: view === "documents" ? "资料库" : "知识库" }]} />
      <header className="catalog-page-header">
        <div className="catalog-page-heading">
          <Title className="catalog-page-title" level={1}>{view === "documents" ? "资料库" : "知识库"}</Title>
        </div>
      </header>
      <SubjectWorkspace onChanged={refresh} subject={subject} view={view} />
    </div>
  );
}

function PaperRoute({ subjects, onGradingChanged }: { subjects: SubjectStatus[]; onGradingChanged: () => Promise<void> }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const paperLocation = parsePaperLocation(pathname);
  if (!paperLocation) {
    return <Result status="404" title="试卷路径无效" extra={<Button onClick={() => navigate("/subjects")}>返回科目列表</Button>} />;
  }
  const subject = subjects.find((item) => item.id === paperLocation.subjectId);
  if (!subject) {
    return <Result status="404" title="科目不存在" extra={<Button onClick={() => navigate("/subjects")}>返回科目列表</Button>} />;
  }
  const { detail } = paperLocation;
  return <PaperManagement
    detail={detail}
    onBackDocument={(subjectId, paperUnitId) => navigate(paperUnitId ? paperDetailPath(subjectId, paperUnitId) : paperIndexPath(subjectId))}
    onCloseDetail={(subjectId) => navigate(detail?.kind === "document" && detail.parentPaperId ? paperDetailPath(subjectId, detail.parentPaperId) : paperIndexPath(subjectId))}
    onOpenDocument={(subjectId, documentId, paperUnitId) => navigate(paperDocumentPath(subjectId, documentId, paperUnitId))}
    onOpenAnswers={(subjectId, paperUnitId) => navigate(paperAnswersPath(subjectId, paperUnitId))}
    onOpenJob={(subjectId, paperUnitId, nextJobId) => navigate(paperAnsweringPath(subjectId, paperUnitId, nextJobId))}
    onOpenPaper={(subjectId, paperUnitId) => navigate(paperDetailPath(subjectId, paperUnitId))}
    onStartAnswering={(subjectId, paperUnitId, nextJobId) => navigate(paperAnsweringPath(subjectId, paperUnitId, nextJobId))}
    onStartGrading={(subjectId, paperUnitId, nextJobId) => navigate(paperGradingPath(subjectId, paperUnitId, nextJobId))}
    onGradingChanged={onGradingChanged}
    onSubjectChange={(subjectId) => navigate(paperIndexPath(subjectId))}
    subjectId={subject.id}
    subjects={subjects}
  />;
}

function LegacyPaperChildRedirect({ subjects }: { subjects: SubjectStatus[] }) {
  const { subjectId } = useParams();
  const resolved = subjectOrFirst(subjects, subjectId);
  if (!resolved) return <Navigate replace to="/subjects" />;
  return <Navigate replace to={paperIndexPath(resolved)} />;
}

function ReviewRoute({ items, loading, refresh }: { items: ReviewItem[]; loading: boolean; refresh: () => Promise<void> }) {
  const navigate = useNavigate();
  const { assessmentId } = useParams();
  const visibleItems = assessmentId ? items.filter((item) => item.id === assessmentId) : items;
  if (assessmentId && visibleItems.length === 0) {
    if (loading) return <Flex align="center" justify="center" style={{ minHeight: 320 }}><Spin size="large" /></Flex>;
    return <Result status="404" title="复核项不存在或已处理" extra={<Button onClick={() => navigate("/reviews")} type="primary">返回复核队列</Button>} />;
  }
  return (
    <Reviews
      focusId={assessmentId}
      items={visibleItems}
      onOpenGrading={(item) => {
        if (item.paper_unit_id && item.paper_job_id) {
          navigate(paperGradingPath(item.subject_id, item.paper_unit_id, item.paper_job_id));
        }
      }}
      onReviewed={assessmentId ? () => navigate("/reviews") : undefined}
      refresh={refresh}
    />
  );
}

function selectedMenuKey(pathname: string) {
  if (pathname.startsWith("/reviews")) return "reviews";
  if (pathname.includes("/papers") || pathname.includes("/documents/")) return "papers";
  return "subjects";
}

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => window.localStorage.getItem("examtwin.sidebar.collapsed") === "true",
  );
  useEffect(() => {
    const root = document.documentElement;
    if (sidebarCollapsed) root.dataset.sidebar = "collapsed";
    else delete root.dataset.sidebar;
  }, [sidebarCollapsed]);
  const platformQuery = useQuery({
    queryKey: ["platform", "subjects"],
    queryFn: () => unwrapApi(apiClient.GET("/api/v1/subjects/status")),
  });
  const reviewsQuery = useQuery({
    queryKey: ["reviews", "pending"],
    queryFn: () => unwrapApi(apiClient.GET("/api/v1/grading/reviews/all")),
  });
  const platform = platformQuery.data as PlatformStatus | undefined;
  const reviews = (reviewsQuery.data ?? []) as ReviewItem[];
  const subjects = platform?.subjects ?? [];
  const routeSubjectId = parseSubjectId(location.pathname);
  useEffect(() => {
    if (routeSubjectId) window.localStorage.setItem(LAST_SUBJECT_STORAGE_KEY, routeSubjectId);
  }, [routeSubjectId]);
  const navSubjectId = subjectOrFirst(
    subjects,
    routeSubjectId ?? window.localStorage.getItem(LAST_SUBJECT_STORAGE_KEY) ?? undefined,
  );
  const paperMenuPath = navSubjectId ? paperIndexPath(navSubjectId) : "/subjects";
  const refreshSubjects = async () => {
    await queryClient.invalidateQueries({ queryKey: ["platform", "subjects"] });
  };
  const refreshReviews = async () => {
    await queryClient.invalidateQueries({ queryKey: ["reviews", "pending"] });
  };
  const loading = platformQuery.isPending;
  const loadError = platformQuery.error ?? reviewsQuery.error;
  const menuItems: AppMenuItem[] = [
    { key: "subjects", icon: <GraduationCap size={17} />, label: "科目", path: "/subjects" },
    { key: "papers", icon: <Files size={17} />, label: "试卷", path: paperMenuPath },
    { key: "reviews", icon: <ShieldCheck size={17} />, label: <Badge count={reviews.length} offset={[10, -3]} size="small">复核</Badge>, path: "/reviews" },
  ];
  const navigateFromNavigation = (path: string) => {
    navigate(path);
  };
  const selectedKey = selectedMenuKey(location.pathname);
  const toggleSidebar = () => {
    setSidebarCollapsed((collapsed) => {
      const next = !collapsed;
      window.localStorage.setItem("examtwin.sidebar.collapsed", String(next));
      return next;
    });
  };

  return (
    <ConversionQueueProvider>
    <Layout hasSider className="app-root">
      <div aria-hidden="true" className="app-ambient-field">
        <span className="app-ambient-orb app-ambient-orb-primary" />
        <span className="app-ambient-orb app-ambient-orb-secondary" />
      </div>

      <aside
        aria-label="应用侧边栏"
        className={`app-desktop-rail${sidebarCollapsed ? " is-collapsed" : ""}`}
      >
        <SidebarNavigation
          collapsed={sidebarCollapsed}
          items={menuItems}
          onNavigate={navigateFromNavigation}
          onToggle={toggleSidebar}
          selectedKey={selectedKey}
        />
      </aside>

      <Layout className="app-main-layout">
        <header className="app-mobile-header">
          <Button
            aria-label="返回科目列表"
            className="app-mobile-brand"
            icon={<span className="app-brand-mark"><img alt="" aria-hidden="true" src="/examtwin-icon.svg" /></span>}
            onClick={() => navigateFromNavigation("/subjects")}
            type="text"
          >
            <Text strong>ExamTwin</Text>
          </Button>
          <div className="app-mobile-theme">
            <span className="sr-only">选择界面主题</span>
            <ThemeSwitch />
          </div>
        </header>

        <Content className="app-page-content">
          <div className="app-page-shell">
            {loadError && (
              <Alert
                action={<Button onClick={() => void Promise.all([refreshSubjects(), refreshReviews()])} size="small">重新加载</Button>}
                closable
                message={loadError instanceof Error ? loadError.message : "数据加载失败"}
                showIcon
                type="error"
              />
            )}
            <Suspense fallback={<Flex align="center" justify="center" style={{ minHeight: 320 }}><Spin description="正在加载" size="large" /></Flex>}>
              <Routes>
                <Route element={<Navigate replace to="/subjects" />} path="/" />
                <Route element={<SubjectManagement loading={loading} onOpenSubject={(subjectId) => navigate(paperIndexPath(subjectId))} refresh={refreshSubjects} subjects={subjects} />} path="/subjects" />
                <Route element={<SubjectOverview subjects={subjects} />} path="/subjects/:subjectId" />
                <Route element={<SubjectWorkspaceRoute refresh={refreshSubjects} subjects={subjects} view="documents" />} path="/subjects/:subjectId/documents" />
                <Route element={<SubjectWorkspaceRoute refresh={refreshSubjects} subjects={subjects} view="knowledge" />} path="/subjects/:subjectId/knowledge" />
                <Route element={<SubjectRedirect subjects={subjects} />} path="/papers" />
                {PAPER_ROUTE_PATTERNS.map((path) => (
                  <Route
                    element={<PaperRoute onGradingChanged={refreshReviews} subjects={subjects} />}
                    key={path}
                    path={path}
                  />
                ))}
                <Route element={<SubjectRedirect subjects={subjects} />} path="/answering" />
                <Route element={<LegacyPaperChildRedirect subjects={subjects} />} path="/subjects/:subjectId/answering" />
                <Route element={<LegacyPaperChildRedirect subjects={subjects} />} path="/subjects/:subjectId/papers/answers" />
                <Route element={<LegacyPaperChildRedirect subjects={subjects} />} path="/subjects/:subjectId/papers/answers/:jobId" />
                <Route element={<SubjectRedirect subjects={subjects} />} path="/grading" />
                <Route element={<LegacyPaperChildRedirect subjects={subjects} />} path="/subjects/:subjectId/grading" />
                <Route element={<LegacyPaperChildRedirect subjects={subjects} />} path="/subjects/:subjectId/papers/:paperUnitId/grading" />
                <Route element={<ReviewRoute items={reviews} loading={reviewsQuery.isPending} refresh={refreshReviews} />} path="/reviews" />
                <Route element={<ReviewRoute items={reviews} loading={reviewsQuery.isPending} refresh={refreshReviews} />} path="/reviews/:assessmentId" />
                <Route element={<Navigate replace to="/subjects" />} path="*" />
              </Routes>
            </Suspense>
          </div>
        </Content>
      </Layout>

      <nav aria-label="主导航" className="app-bottom-nav">
        {menuItems.map((item) => (
          <button
            aria-current={selectedKey === item.key ? "page" : undefined}
            className={selectedKey === item.key ? "is-active" : undefined}
            key={item.key}
            onClick={() => navigateFromNavigation(item.path)}
            type="button"
          >
            <span aria-hidden="true" className="app-bottom-nav-icon">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </Layout>
    </ConversionQueueProvider>
  );
}
