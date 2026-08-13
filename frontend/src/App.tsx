import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Breadcrumb,
  Button,
  Card,
  Col,
  Flex,
  Layout,
  Menu,
  Result,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import {
  BookOpenCheck,
  FileText,
  Files,
  GraduationCap,
  LibraryBig,
  ShieldCheck,
} from "lucide-react";
import { lazy, Suspense } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router";

import { SubjectWorkspace } from "./components/SubjectWorkspace";
import { ThemeSwitch } from "./components/ThemeSwitch";
import { apiClient, unwrapApi } from "./lib/api";
import type { PlatformStatus, ReviewItem, SubjectStatus } from "./types";

const SubjectManagement = lazy(() => import("./pages/SubjectManagement").then(({ SubjectManagement: Page }) => ({ default: Page })));
const PaperManagement = lazy(() => import("./pages/PaperManagement").then(({ PaperManagement: Page }) => ({ default: Page })));
const PaperAnswering = lazy(() => import("./pages/PaperAnswering").then(({ PaperAnswering: Page }) => ({ default: Page })));
const Grading = lazy(() => import("./pages/Grading").then(({ Grading: Page }) => ({ default: Page })));
const Reviews = lazy(() => import("./pages/Reviews").then(({ Reviews: Page }) => ({ default: Page })));

const { Content, Header } = Layout;
const { Paragraph, Text, Title } = Typography;

function subjectOrFirst(subjects: SubjectStatus[], requested?: string) {
  return subjects.find((item) => item.id === requested)?.id ?? subjects[0]?.id ?? "";
}

function encoded(value: string) {
  return encodeURIComponent(value);
}

function SubjectRedirect({ subjects, task }: { subjects: SubjectStatus[]; task: "papers" | "answering" | "grading" }) {
  const subjectId = subjects[0]?.id;
  if (!subjectId) return <Navigate replace to="/subjects" />;
  return <Navigate replace to={`/subjects/${encoded(subjectId)}/${task}`} />;
}

function SubjectOverview({ subjects }: { subjects: SubjectStatus[] }) {
  const navigate = useNavigate();
  const { subjectId = "" } = useParams();
  const subject = subjects.find((item) => item.id === subjectId);
  if (!subject) {
    return <Result status="404" title="科目不存在" subTitle="该 URL 中的科目标识无效或科目已被删除。" extra={<Button onClick={() => navigate("/subjects")} type="primary">返回科目列表</Button>} />;
  }
  const base = `/subjects/${encoded(subject.id)}`;
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Breadcrumb items={[{ title: "科目" }, { title: subject.title }]} />
      <Flex align="center" justify="space-between" wrap gap="middle">
        <Space direction="vertical" size={0}>
          <Space wrap>
            <Tag color="blue">{subject.subject_code}</Tag>
            <Text type="secondary">{subject.board_name}</Text>
          </Space>
          <Title level={2} style={{ margin: 0 }}>{subject.title}</Title>
          <Paragraph type="secondary">科目资料、知识库、试卷、作答与评分的统一入口。</Paragraph>
        </Space>
        <Button onClick={() => navigate(`${base}/papers`)} size="large" type="primary">进入试卷库</Button>
      </Flex>
      <Row gutter={[16, 16]}>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="documents" onClick={() => navigate(`${base}/documents`)} type="link">管理资料</Button>]}>
            <Card.Meta avatar={<Files size={24} />} title="资料库" description="大纲、教材、Question Paper、Mark Scheme 与 Source Booklet。" />
          </Card>
        </Col>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="knowledge" onClick={() => navigate(`${base}/knowledge`)} type="link">查看知识库</Button>]}>
            <Card.Meta avatar={<LibraryBig size={24} />} title="知识库" description="维护授权资料并构建当前科目的可检索知识版本。" />
          </Card>
        </Col>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="papers" onClick={() => navigate(`${base}/papers`)} type="link">打开试卷库</Button>]}>
            <Card.Meta avatar={<FileText size={24} />} title="试卷库" description="管理严格配对的试卷、评分标准和支撑材料。" />
          </Card>
        </Col>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="answering" onClick={() => navigate(`${base}/answering`)} type="link">进入作答</Button>]}>
            <Card.Meta avatar={<GraduationCap size={24} />} title="作答任务" description="上传试卷或继续该科目已有的作答任务。" />
          </Card>
        </Col>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="grading" onClick={() => navigate(`${base}/grading`)} type="link">进入评分</Button>]}>
            <Card.Meta avatar={<BookOpenCheck size={24} />} title="评分任务" description="绑定评分标准，逐题判分并进入人工复核。" />
          </Card>
        </Col>
      </Row>
    </Space>
  );
}

function SubjectWorkspaceRoute({ subjects, refresh, view }: { subjects: SubjectStatus[]; refresh: () => Promise<void>; view: "documents" | "knowledge" }) {
  const navigate = useNavigate();
  const { subjectId = "" } = useParams();
  const subject = subjects.find((item) => item.id === subjectId);
  if (!subject) return <Result status="404" title="科目不存在" extra={<Button onClick={() => navigate("/subjects")}>返回科目列表</Button>} />;
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Breadcrumb items={[{ title: <Button onClick={() => navigate("/subjects")} type="link">科目</Button> }, { title: <Button onClick={() => navigate(`/subjects/${encoded(subject.id)}`)} type="link">{subject.title}</Button> }, { title: view === "documents" ? "资料库" : "知识库" }]} />
      <Title level={2}>{view === "documents" ? "资料库" : "知识库"}</Title>
      <SubjectWorkspace onChanged={refresh} subject={subject} view={view} />
    </Space>
  );
}

function PaperRoute({ subjects }: { subjects: SubjectStatus[] }) {
  const navigate = useNavigate();
  const params = useParams();
  const selectedSubjectId = subjectOrFirst(subjects, params.subjectId);
  if (!selectedSubjectId) return <Result title="尚未创建科目" subTitle="创建科目后才能管理试卷。" />;
  const jobId = params.jobId ?? "";
  const detail = params.paperUnitId && jobId
    ? { kind: "job" as const, id: jobId }
    : params.paperUnitId
      ? { kind: "paper" as const, id: params.paperUnitId }
      : params.documentId
        ? { kind: "document" as const, id: params.documentId }
        : null;
  return <PaperManagement
    detail={detail}
    onCloseDetail={(subjectId) => navigate(`/subjects/${encoded(subjectId)}/papers`)}
    onOpenDocument={(subjectId, documentId) => navigate(`/subjects/${encoded(subjectId)}/documents/${encoded(documentId)}`)}
    onOpenJob={(subjectId, paperUnitId, nextJobId) => navigate(`/subjects/${encoded(subjectId)}/papers/${encoded(paperUnitId)}/jobs/${encoded(nextJobId)}`)}
    onOpenPaper={(subjectId, paperUnitId) => navigate(`/subjects/${encoded(subjectId)}/papers/${encoded(paperUnitId)}`)}
    onStartAnswering={(subjectId, paperUnitId, nextJobId) => navigate(`/subjects/${encoded(subjectId)}/papers/${encoded(paperUnitId)}/jobs/${encoded(nextJobId)}/answering`)}
    onStartGrading={(subjectId, paperUnitId) => navigate(`/subjects/${encoded(subjectId)}/papers/${encoded(paperUnitId)}/grading`)}
    onSubjectChange={(subjectId) => navigate(`/subjects/${encoded(subjectId)}/papers`)}
    subjectId={selectedSubjectId}
    subjects={subjects}
  />;
}

function AnsweringRoute({ subjects }: { subjects: SubjectStatus[] }) {
  const params = useParams();
  const subjectId = subjectOrFirst(subjects, params.subjectId);
  const subject = subjects.find((item) => item.id === subjectId);
  if (!subject) return <Result status="404" title="科目不存在" />;
  return <PaperAnswering enabled={subject.answering_enabled} initialJobId={params.jobId} initialSubjectId={subject.id} subjects={subjects} />;
}

function GradingRoute({ subjects, onCreated }: { subjects: SubjectStatus[]; onCreated: () => Promise<void> }) {
  const params = useParams();
  const subjectId = subjectOrFirst(subjects, params.subjectId);
  if (!subjectId) return <Result status="404" title="科目不存在" />;
  return <Grading initialPaperUnitId={params.paperUnitId} initialSubjectId={subjectId} onCreated={onCreated} subjects={subjects} />;
}

function ReviewRoute({ items, refresh }: { items: ReviewItem[]; refresh: () => Promise<void> }) {
  const { assessmentId } = useParams();
  const visibleItems = assessmentId ? items.filter((item) => item.id === assessmentId) : items;
  if (assessmentId && visibleItems.length === 0) return <Result status="404" title="复核项不存在" />;
  return <Reviews items={visibleItems} refresh={refresh} />;
}

function selectedMenuKey(pathname: string) {
  if (pathname.startsWith("/reviews")) return "reviews";
  if (pathname.includes("/grading")) return "grading";
  if (pathname.includes("/answering")) return "answering";
  if (pathname.includes("/papers") || pathname.includes("/documents/")) return "papers";
  return "subjects";
}

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
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
  const currentSubjectId = location.pathname.match(/^\/subjects\/([^/]+)/)?.[1];
  const navSubjectId = subjectOrFirst(subjects, currentSubjectId ? decodeURIComponent(currentSubjectId) : undefined);
  const subjectBase = navSubjectId ? `/subjects/${encoded(navSubjectId)}` : "/subjects";
  const refreshSubjects = async () => {
    await queryClient.invalidateQueries({ queryKey: ["platform", "subjects"] });
  };
  const refreshReviews = async () => {
    await queryClient.invalidateQueries({ queryKey: ["reviews", "pending"] });
  };
  const loading = platformQuery.isPending;
  const loadError = platformQuery.error ?? reviewsQuery.error;
  const menuItems = [
    { key: "subjects", icon: <GraduationCap size={17} />, label: "科目", path: "/subjects" },
    { key: "papers", icon: <Files size={17} />, label: "试卷", path: `${subjectBase}/papers` },
    { key: "answering", icon: <FileText size={17} />, label: "作答", path: `${subjectBase}/answering` },
    { key: "grading", icon: <BookOpenCheck size={17} />, label: "评分", path: `${subjectBase}/grading` },
    { key: "reviews", icon: <ShieldCheck size={17} />, label: <Badge count={reviews.length} offset={[10, -3]} size="small">复核</Badge>, path: "/reviews" },
  ];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header className="app-topbar" style={{ alignItems: "center", background: "#fff", borderBottom: "1px solid #f0f0f0", display: "flex", gap: 24, height: "auto", minHeight: 64, paddingInline: 24 }}>
        <Button icon={<LibraryBig size={20} />} onClick={() => navigate("/subjects")} size="large" type="text">
          <Text strong>ExamTwin</Text>
        </Button>
        <nav aria-label="主导航" className="app-topbar-nav">
          <Menu
            items={menuItems.map(({ key, icon, label }) => ({ key, icon, label }))}
            mode="horizontal"
            onClick={({ key }) => navigate(menuItems.find((item) => item.key === key)?.path ?? "/subjects")}
            selectedKeys={[selectedMenuKey(location.pathname)]}
            style={{ minWidth: 0 }}
          />
        </nav>
        <ThemeSwitch />
      </Header>
      <Content style={{ marginInline: "auto", maxWidth: 1440, padding: "24px clamp(16px, 3vw, 40px) 48px", width: "100%" }}>
        {loadError && <Alert closable message={loadError instanceof Error ? loadError.message : "数据加载失败"} showIcon type="error" />}
        <Suspense fallback={<Flex align="center" justify="center" style={{ minHeight: 320 }}><Spin size="large" tip="正在加载" /></Flex>}>
          <Routes>
            <Route element={<Navigate replace to="/subjects" />} path="/" />
            <Route element={<SubjectManagement loading={loading} refresh={refreshSubjects} subjects={subjects} />} path="/subjects" />
            <Route element={<SubjectOverview subjects={subjects} />} path="/subjects/:subjectId" />
            <Route element={<SubjectWorkspaceRoute refresh={refreshSubjects} subjects={subjects} view="documents" />} path="/subjects/:subjectId/documents" />
            <Route element={<SubjectWorkspaceRoute refresh={refreshSubjects} subjects={subjects} view="knowledge" />} path="/subjects/:subjectId/knowledge" />
            <Route element={<SubjectRedirect subjects={subjects} task="papers" />} path="/papers" />
            <Route element={<PaperRoute subjects={subjects} />} path="/subjects/:subjectId/papers" />
            <Route element={<PaperRoute subjects={subjects} />} path="/subjects/:subjectId/papers/:paperUnitId" />
            <Route element={<PaperRoute subjects={subjects} />} path="/subjects/:subjectId/documents/:documentId" />
            <Route element={<SubjectRedirect subjects={subjects} task="answering" />} path="/answering" />
            <Route element={<AnsweringRoute subjects={subjects} />} path="/subjects/:subjectId/answering" />
            <Route element={<PaperRoute subjects={subjects} />} path="/subjects/:subjectId/papers/:paperUnitId/jobs/:jobId" />
            <Route element={<AnsweringRoute subjects={subjects} />} path="/subjects/:subjectId/papers/:paperUnitId/jobs/:jobId/answering" />
            <Route element={<SubjectRedirect subjects={subjects} task="grading" />} path="/grading" />
            <Route element={<GradingRoute onCreated={refreshReviews} subjects={subjects} />} path="/subjects/:subjectId/grading" />
            <Route element={<GradingRoute onCreated={refreshReviews} subjects={subjects} />} path="/subjects/:subjectId/papers/:paperUnitId/grading" />
            <Route element={<ReviewRoute items={reviews} refresh={refreshReviews} />} path="/reviews" />
            <Route element={<ReviewRoute items={reviews} refresh={refreshReviews} />} path="/reviews/:assessmentId" />
            <Route element={<Navigate replace to="/subjects" />} path="*" />
          </Routes>
        </Suspense>
      </Content>
    </Layout>
  );
}
