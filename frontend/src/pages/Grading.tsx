import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { GradingMaterialsStage } from "../components/grading/GradingMaterialsStage";
import { GradingOverview } from "../components/grading/GradingOverview";
import { GradingQuestionStage } from "../components/grading/GradingQuestionStage";
import { RubricReviewStage } from "../components/grading/RubricReviewStage";
import { useToast } from "../components/toast-context";
import { AppDialog } from "../components/ui/AppDialog";
import { AppConfirmDialog } from "../components/ui/AppConfirmDialog";
import {
  apiClient,
  deletePaperJobs,
  importAnsweredPaper,
  renamePaperJob,
  renameWorkspaceDocument,
  subjectHeaders,
  unwrapApi,
  uploadWorkspaceDocument,
} from "../lib/api";
import {
  subscribeTaskSnapshots,
  type TaskStreamState,
} from "../lib/task-events";
import type {
  AiReviewRubricCriteriaRequest,
  BatchReviewRubricCriteriaRequest,
  GradeResult,
  GradingOverviewResponse,
  GradingPaper,
  PaperAssessment,
  PaperJobResult,
  RubricCriterionPatch,
  RubricSet,
  RubricSetSummary,
  SourceDocument,
  SubjectPack,
} from "../types";

type GradingStep = 1 | 3 | 4;
const REVIEWER_STORAGE_KEY = "examtwin.reviewerName";
const MAX_BATCH_REVIEW_CRITERIA = 200;

export function Grading({
  subjects: providedSubjects,
  subject: legacySubject,
  onCreated,
  initialSubjectId,
  initialPaperUnitId,
}: {
  subjects?: SubjectPack[];
  subject?: SubjectPack | null;
  onCreated: () => Promise<void>;
  initialSubjectId?: string;
  initialPaperUnitId?: string;
}) {
  const subjects = providedSubjects ?? (legacySubject ? [legacySubject] : []);
  const legacyMode = providedSubjects === undefined;
  const routedContext = Boolean(initialSubjectId);
  const [subjectId, setSubjectId] = useState(initialSubjectId ?? legacySubject?.id ?? "");
  const subject = subjects.find((item) => item.id === subjectId) ?? null;
  const [papers, setPapers] = useState<GradingPaper[]>([]);
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [papersLoading, setPapersLoading] = useState(true);
  const [papersError, setPapersError] = useState<string | null>(null);
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const importStorageKey = `examtwin.gradingImportJobId.${subjectId || "unselected"}`;
  const [importJobId, setImportJobId] = useState<string | null>(() =>
    window.localStorage.getItem(importStorageKey)
  );
  const [importJob, setImportJob] = useState<PaperJobResult | null>(null);
  const [importStreamState, setImportStreamState] = useState<TaskStreamState>("idle");
  const [importStreamVersion, setImportStreamVersion] = useState(0);
  const [paperId, setPaperId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [paper, setPaper] = useState<PaperJobResult | null>(null);
  const [rubrics, setRubrics] = useState<RubricSetSummary[]>([]);
  const [rubric, setRubric] = useState<RubricSet | null>(null);
  const [assessments, setAssessments] = useState<PaperAssessment[]>([]);
  const [overview, setOverview] = useState<GradingOverviewResponse | null>(null);
  const [selectedPosition, setSelectedPosition] = useState<number | null>(null);
  const [step, setStep] = useState<GradingStep>(1);
  const [rubricReviewOpen, setRubricReviewOpen] = useState(false);
  const [generateSchemeConfirmOpen, setGenerateSchemeConfirmOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [overviewBusy, setOverviewBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState(() =>
    window.localStorage.getItem(REVIEWER_STORAGE_KEY) ?? ""
  );
  const paperRequestRef = useRef(0);
  const paperDiscoveryRequestRef = useRef(0);
  const sourceRequestRef = useRef(0);
  const rubricRequestRef = useRef(0);
  const rubricCreationRequestRef = useRef(0);
  const overviewRequestRef = useRef(0);
  const uploadRequestRef = useRef(0);
  const busyOperationRef = useRef(0);
  const assessmentRequestRef = useRef(0);
  const reconciliationRequestRef = useRef(0);
  const pendingDiscoveredDocumentRef = useRef<{
    paperId: string;
    documentId: string;
  } | null>(null);
  const paperIdRef = useRef(paperId);
  const documentIdRef = useRef(documentId);
  const documentSelectionRevisionRef = useRef(0);
  const documentSelectionExplicitRef = useRef(false);
  const readyDocumentIdsRef = useRef<ReadonlySet<string>>(new Set());
  const rubricIdRef = useRef<string | null>(null);
  const pageRef = useRef<HTMLElement>(null);
  const stepRef = useRef<GradingStep>(step);
  const focusStageAfterRenderRef = useRef(false);
  paperIdRef.current = paperId;
  documentIdRef.current = documentId;
  stepRef.current = step;
  rubricIdRef.current = rubric?.paper_job_id === paperId
    && rubric.source_document_id === documentId
    ? rubric.id
    : null;
  const { notify } = useToast();

  const beginBusy = useCallback((label: string) => {
    const operationId = ++busyOperationRef.current;
    setBusy(label);
    return operationId;
  }, []);

  const finishBusy = useCallback((operationId: number) => {
    if (operationId === busyOperationRef.current) setBusy(null);
  }, []);

  const clearPaperContextState = useCallback(() => {
    setPaper(null);
    setRubrics([]);
    setRubric(null);
    setAssessments([]);
    setOverview(null);
    setSelectedPosition(null);
    busyOperationRef.current += 1;
    setBusy(null);
    setOverviewBusy(false);
    setError(null);
    setOverviewError(null);
  }, []);

  const loadSources = useCallback(async (preserveSelection = false) => {
    if (!subjectId) return;
    const requestId = ++sourceRequestRef.current;
    setDocumentsLoading(true);
    try {
      const rows = await unwrapApi(
        apiClient.GET("/api/v1/corpus/documents", {
          headers: subjectHeaders(subjectId),
          params: { query: { source_type: "mark_scheme", limit: 100 } },
        }),
      );
      if (requestId !== sourceRequestRef.current) return;
      const readyRows = (rows as SourceDocument[]).filter(
        (item) => item.status === "converted" || item.status === "indexed",
      );
      readyDocumentIdsRef.current = new Set(readyRows.map((item) => String(item.id)));
      setDocuments(readyRows);
      setDocumentsError(null);
      if (
        !preserveSelection
        && !readyRows.some((item) => String(item.id) === documentIdRef.current)
      ) {
        const firstDocumentId = readyRows.length ? String(readyRows[0].id) : "";
        documentSelectionExplicitRef.current = false;
        pendingDiscoveredDocumentRef.current = firstDocumentId && paperIdRef.current
          ? { paperId: paperIdRef.current, documentId: firstDocumentId }
          : null;
        documentIdRef.current = firstDocumentId;
        setDocumentId(firstDocumentId);
      }
      return readyRows;
    } catch (cause) {
      if (requestId !== sourceRequestRef.current) return;
      setDocumentsError(cause instanceof Error ? cause.message : "Mark Scheme 列表加载失败");
      throw cause;
    } finally {
      if (requestId === sourceRequestRef.current) setDocumentsLoading(false);
    }
  }, [subjectId]);

  const loadPapers = useCallback(async (preferredPaperId?: string) => {
    if (!subjectId) return;
    const requestId = ++paperDiscoveryRequestRef.current;
    setPapersLoading(true);
    try {
      const rows = await unwrapApi(apiClient.GET("/api/v1/grading/papers", {
        headers: subjectHeaders(subjectId),
        params: { query: { paper_unit_id: initialPaperUnitId } },
      }));
      if (requestId !== paperDiscoveryRequestRef.current) return;
      setPapers(rows);
      setPapersError(null);
      const nextPaperId = preferredPaperId && rows.some(
        (item) => item.job_id === preferredPaperId,
      )
        ? preferredPaperId
        : rows.some((item) => item.job_id === paperIdRef.current)
          ? paperIdRef.current
          : rows[0]?.job_id ?? "";
      if (nextPaperId !== paperIdRef.current) {
        clearPaperContextState();
        paperIdRef.current = nextPaperId;
        setPaperId(nextPaperId);
      }
    } catch (cause) {
      if (requestId !== paperDiscoveryRequestRef.current) return;
      setPapersError(cause instanceof Error ? cause.message : "作答记录列表加载失败");
      throw cause;
    } finally {
      if (requestId === paperDiscoveryRequestRef.current) setPapersLoading(false);
    }
  }, [clearPaperContextState, initialPaperUnitId, subjectId]);

  useEffect(() => {
    if (!initialSubjectId) return;
    setSubjectId(initialSubjectId);
  }, [initialSubjectId]);

  useEffect(() => {
    setImportJobId(window.localStorage.getItem(importStorageKey));
    setImportJob(null);
    setImportStreamState("idle");
  }, [importStorageKey]);

  useEffect(() => {
    if (!importJobId || !subject) return;
    return subscribeTaskSnapshots<PaperJobResult>({
      subjectId: subject.id,
      path: `/papers/jobs/${importJobId}/events`,
      onSnapshot: (next) => {
        setImportJob(next);
        if (["completed", "partial_failed"].includes(next.status)) {
          window.localStorage.removeItem(importStorageKey);
          void loadPapers(next.job_id).then(() => {
            notify(
              next.status === "completed"
                ? `上传答卷解析完成：${next.completed_questions} 题已进入作答记录。`
                : `上传答卷解析结束：${next.completed_questions} 题可评分，${next.failed_questions} 题失败。`,
            );
          });
        }
      },
      isTerminal: (next) =>
        ["completed", "partial_failed", "failed"].includes(next.status),
      onState: setImportStreamState,
      onUnavailable: (message) => {
        window.localStorage.removeItem(importStorageKey);
        setImportJobId(null);
        setImportJob(null);
        setError(message);
      },
      onError: setError,
    });
  }, [importJobId, importStorageKey, importStreamVersion, loadPapers, notify, subject]);

  const loadDiscoveryLists = useCallback(async () => {
    await Promise.allSettled([loadPapers(), loadSources()]);
  }, [loadPapers, loadSources]);

  const loadOverview = useCallback(async (
    nextPaperId: string,
    nextDocumentId: string,
    rubricId: string,
  ) => {
    const requestId = ++overviewRequestRef.current;
    if (!subjectId) return;
    setOverviewBusy(true);
    setOverviewError(null);
    try {
      const nextOverview = await unwrapApi(
        apiClient.GET("/api/v1/grading/papers/{paper_job_id}/overview", {
          headers: subjectHeaders(subjectId),
          params: {
            path: { paper_job_id: nextPaperId },
            query: { rubric_set_id: rubricId },
          },
        }),
      );
      if (
        requestId !== overviewRequestRef.current
        || paperIdRef.current !== nextPaperId
        || documentIdRef.current !== nextDocumentId
        || rubricIdRef.current !== rubricId
      ) return;
      if (
        nextOverview.paper_job_id !== nextPaperId
        || nextOverview.rubric_set_id !== rubricId
      ) {
        setOverviewError("整卷总览与当前答卷或评分规则不匹配，请重新刷新。");
        return;
      }
      setOverview(nextOverview);
    } catch (cause) {
      if (
        requestId !== overviewRequestRef.current
        || paperIdRef.current !== nextPaperId
        || documentIdRef.current !== nextDocumentId
        || rubricIdRef.current !== rubricId
      ) return;
      setOverviewError(cause instanceof Error ? cause.message : "整卷总览加载失败");
    } finally {
      if (requestId === overviewRequestRef.current) setOverviewBusy(false);
    }
  }, [subjectId]);

  const loadPaperContext = useCallback(async (nextPaperId: string) => {
    if (!subjectId) return;
    const requestId = ++paperRequestRef.current;
    const documentRevision = documentSelectionRevisionRef.current;
    rubricRequestRef.current += 1;
    overviewRequestRef.current += 1;
    assessmentRequestRef.current += 1;
    reconciliationRequestRef.current += 1;
    setOverviewBusy(false);
    if (!nextPaperId) {
      clearPaperContextState();
      return;
    }
    const operationId = beginBusy("loading-paper");
    setError(null);
    setOverview(null);
    setOverviewError(null);
    try {
      const [nextPaper, nextRubrics, nextAssessments] = await Promise.all([
        unwrapApi(
          apiClient.GET("/api/v1/papers/jobs/{job_id}", {
            headers: subjectHeaders(subjectId),
            params: { path: { job_id: nextPaperId } },
          }),
        ),
        unwrapApi(
          apiClient.GET("/api/v1/grading/rubrics", {
            headers: subjectHeaders(subjectId),
            params: { query: { paper_job_id: nextPaperId } },
          }),
        ),
        unwrapApi(
          apiClient.GET("/api/v1/grading/papers/{paper_job_id}/assessments", {
            headers: subjectHeaders(subjectId),
            params: { path: { paper_job_id: nextPaperId } },
          }),
        ),
      ]);
      if (requestId !== paperRequestRef.current) return;
      const matchingRubrics = nextRubrics.filter(
        (item) => item.paper_job_id === nextPaperId,
      );
      const selectedDocumentId = documentIdRef.current;
      const pairedSummary = matchingRubrics.find(
        (item) => item.source_document_id === selectedDocumentId,
      ) ?? (
        !documentSelectionExplicitRef.current
        && documentRevision === documentSelectionRevisionRef.current
          ? matchingRubrics.find(
              (item) => readyDocumentIdsRef.current.has(item.source_document_id),
            )
          : undefined
      );
      const nextRubric = pairedSummary
        ? await unwrapApi(
            apiClient.GET("/api/v1/grading/rubrics/{rubric_id}", {
              headers: subjectHeaders(subjectId),
              params: { path: { rubric_id: pairedSummary.id } },
            }),
          )
        : null;
      if (
        requestId !== paperRequestRef.current
        || documentRevision !== documentSelectionRevisionRef.current
      ) return;
      if (
        nextPaper.job_id !== nextPaperId
        || (
          nextRubric
          && (
            nextRubric.paper_job_id !== nextPaperId
            || nextRubric.source_document_id !== pairedSummary?.source_document_id
          )
        )
      ) {
        setError("加载的评分数据与所选答卷或 Mark Scheme 不匹配，请重新选择。");
        return;
      }
      const pairedDocumentId = nextRubric?.source_document_id ?? selectedDocumentId;
      if (pairedDocumentId !== documentIdRef.current) {
        documentIdRef.current = pairedDocumentId;
        setDocumentId(pairedDocumentId);
      }
      setPaper(nextPaper as PaperJobResult);
      setRubrics(matchingRubrics);
      setAssessments(nextAssessments.filter(
        (item) => item.paper_job_id === nextPaperId,
      ));
      setSelectedPosition(
        nextPaper.questions.find((item) => item.status === "completed")?.position ?? null,
      );
      setRubric(nextRubric);
      rubricIdRef.current = nextRubric?.id ?? null;
      if (nextRubric?.status === "confirmed") {
        void loadOverview(nextPaperId, pairedDocumentId, nextRubric.id);
      }
    } catch (cause) {
      if (requestId !== paperRequestRef.current) return;
      setError(cause instanceof Error ? cause.message : "评分工作区加载失败");
    } finally {
      if (requestId === paperRequestRef.current) finishBusy(operationId);
    }
  }, [beginBusy, clearPaperContextState, finishBusy, loadOverview, subjectId]);

  useEffect(() => {
    if (!subject) return;
    void loadDiscoveryLists();
    return () => {
      paperDiscoveryRequestRef.current += 1;
      sourceRequestRef.current += 1;
    };
  }, [loadDiscoveryLists, subject]);

  useEffect(() => {
    if (!subject) return;
    void loadPaperContext(paperId);
    return () => {
      paperRequestRef.current += 1;
      rubricRequestRef.current += 1;
      rubricCreationRequestRef.current += 1;
      uploadRequestRef.current += 1;
      assessmentRequestRef.current += 1;
      reconciliationRequestRef.current += 1;
      overviewRequestRef.current += 1;
    };
  }, [loadPaperContext, paperId, subject]);

  useLayoutEffect(() => {
    if (!focusStageAfterRenderRef.current) return;
    focusStageAfterRenderRef.current = false;
    const heading = pageRef.current?.querySelector<HTMLElement>(
      `#grading-stage-${step}-heading`,
    ) ?? pageRef.current?.querySelector<HTMLElement>(".grading-stage-header h2");
    if (!heading) return;
    if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
    heading.focus();
  }, [step]);

  const activePaper = paper?.job_id === paperId ? paper : null;
  const activeRubric = rubric?.paper_job_id === paperId
    && rubric.source_document_id === documentId
    ? rubric
    : null;
  const activeAssessments = activePaper && activeRubric
    ? assessments.filter(
        (item) =>
          item.paper_job_id === paperId
          && item.rubric_set_id === activeRubric.id,
      )
    : [];
  const contextLoading = busy === "loading-paper"
    || busy === "loading-rubric"
    || busy === "upload"
    || busy === "create-rubric";
  const rubricWritePending = busy !== null && (
    busy.startsWith("review-")
    || busy === "batch-review"
    || busy === "ai-review"
    || busy === "confirm-rubric"
  );
  const assessmentWritePending = busy?.startsWith("grade-") ?? false;
  const journeyLocked = contextLoading || rubricWritePending || assessmentWritePending;
  const closeRubricReview = useCallback(() => {
    if (rubricWritePending) return;
    setRubricReviewOpen(false);
    if (rubricIdRef.current && rubric?.status !== "confirmed") {
      stepRef.current = 1;
      setStep(1);
    }
  }, [rubric?.status, rubricWritePending]);

  function transitionToStep(
    nextStep: GradingStep,
    contextRubric: RubricSet | null = activeRubric,
    allowWhileLocked = false,
  ) {
    if (journeyLocked && !allowWhileLocked) return;
    if (nextStep === stepRef.current) return;
    if (nextStep > 1 && !contextRubric) return;
    if (nextStep > 2 && contextRubric?.status !== "confirmed") return;
    focusStageAfterRenderRef.current = true;
    stepRef.current = nextStep;
    setStep(nextStep);
  }

  function choosePaper(nextPaperId: string) {
    if (nextPaperId === paperIdRef.current) return;
    documentSelectionExplicitRef.current = false;
    pendingDiscoveredDocumentRef.current = null;
    paperRequestRef.current += 1;
    rubricRequestRef.current += 1;
    rubricCreationRequestRef.current += 1;
    uploadRequestRef.current += 1;
    overviewRequestRef.current += 1;
    assessmentRequestRef.current += 1;
    reconciliationRequestRef.current += 1;
    paperIdRef.current = nextPaperId;
    rubricIdRef.current = null;
    clearPaperContextState();
    setPaperId(nextPaperId);
    setRubricReviewOpen(false);
    stepRef.current = 1;
    setStep(1);
  }

  function chooseDocument(nextDocumentId: string) {
    if (nextDocumentId === documentIdRef.current) return;
    documentSelectionExplicitRef.current = true;
    pendingDiscoveredDocumentRef.current = null;
    rubricRequestRef.current += 1;
    rubricCreationRequestRef.current += 1;
    uploadRequestRef.current += 1;
    assessmentRequestRef.current += 1;
    reconciliationRequestRef.current += 1;
    overviewRequestRef.current += 1;
    documentSelectionRevisionRef.current += 1;
    busyOperationRef.current += 1;
    documentIdRef.current = nextDocumentId;
    rubricIdRef.current = null;
    setDocumentId(nextDocumentId);
    setRubric(null);
    setAssessments([]);
    setSelectedPosition(null);
    setOverview(null);
    setOverviewBusy(false);
    setOverviewError(null);
    setBusy(null);
    setError(null);
    setRubricReviewOpen(false);
    setStep(1);
    stepRef.current = 1;

    if (!activePaper && paperIdRef.current) {
      void loadPaperContext(paperIdRef.current);
      return;
    }
    const matchingRubric = rubrics.find(
      (item) =>
        item.paper_job_id === paperIdRef.current
        && item.source_document_id === nextDocumentId,
    );
    if (matchingRubric) void selectRubric(matchingRubric.id);
  }

  async function prepareRubric() {
    if (contextLoading) return;
    if (!activePaper) {
      const activePaperId = paperIdRef.current;
      if (!activePaperId) return;
      await loadPaperContext(activePaperId);
      return;
    }
    if (
      activeRubric
      && activeRubric.source_document_id === documentId
    ) {
      if (activeRubric.status === "confirmed") transitionToStep(3);
      else setRubricReviewOpen(true);
      return;
    }
    await createRubric();
  }

  async function importExternalAnswer(
    questionFile: File,
    answerFile: File,
    sourceBooklet?: File | null,
  ) {
    const operationId = beginBusy("import-answer");
    setError(null);
    try {
      const created = await importAnsweredPaper(subjectId, questionFile, answerFile, "", sourceBooklet);
      window.localStorage.setItem(importStorageKey, created.job_id);
      setImportJobId(created.job_id);
      setImportJob(null);
      setImportStreamVersion((version) => version + 1);
      notify(`答卷已导入，任务 ${created.job_id.slice(0, 8)} 正在后台解析。`);
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "答卷导入失败");
      return false;
    } finally {
      finishBusy(operationId);
    }
  }

  async function deletePaperMaterial(deletingPaperId: string) {
    try {
      await deletePaperJobs(subjectId, [deletingPaperId]);
      if (paperIdRef.current === deletingPaperId) choosePaper("");
      await Promise.all([loadPapers(), onCreated()]);
      notify("作答记录已删除。");
    } catch (cause) {
      throw new Error(cause instanceof Error ? cause.message : "作答记录删除失败");
    }
  }

  async function deleteSchemeMaterial(deletingDocumentId: string) {
    if (!subject) return;
    try {
      await unwrapApi(
        apiClient.DELETE("/api/v1/subject-workspaces/{workspace_id}/documents/{document_id}", {
          headers: subjectHeaders(subject.id),
          params: {
            path: { workspace_id: subject.id, document_id: deletingDocumentId },
          },
        }),
      );
      const deletingCurrent = documentIdRef.current === deletingDocumentId;
      if (deletingCurrent) chooseDocument("");
      setDocuments((items) => items.filter(
        (item) => String(item.id) !== deletingDocumentId,
      ));
      notify("Mark Scheme 已从可用材料中删除。");
      void Promise.allSettled([loadSources(true), onCreated()]);
    } catch (cause) {
      throw new Error(cause instanceof Error ? cause.message : "Mark Scheme 删除失败");
    }
  }

  async function renamePaperMaterial(renamingPaperId: string, displayName: string) {
    const renamed = await renamePaperJob(subjectId, renamingPaperId, displayName);
    setPapers((items) => items.map((item) => (
      item.job_id === renamingPaperId
        ? { ...item, display_name: renamed.display_name }
        : item
    )));
    if (paperIdRef.current === renamingPaperId) setPaper(renamed);
    notify("作答记录名称已更新。");
  }

  async function renameSchemeMaterial(renamingDocumentId: string, displayName: string) {
    if (!subject) return;
    const renamed = await renameWorkspaceDocument(
      subject.id,
      renamingDocumentId,
      displayName,
    );
    setDocuments((items) => items.map((item) => (
      item.id === renamingDocumentId ? { ...item, ...renamed } : item
    )));
    notify("Mark Scheme 名称已更新。");
  }

  async function uploadScheme(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !subject) return;
    const requestId = ++uploadRequestRef.current;
    rubricCreationRequestRef.current += 1;
    const selectionRevision = documentSelectionRevisionRef.current;
    const activeDocumentId = documentIdRef.current;
    const operationId = beginBusy("upload");
    setError(null);
    try {
      const uploaded = await uploadWorkspaceDocument(subject.id, file, "mark_scheme");
      const conversion = await unwrapApi(
        apiClient.POST("/api/v1/corpus/convert", {
          headers: subjectHeaders(subject.id),
          body: {
            authority_tiers: [],
            document_ids: [uploaded.id],
            force: false,
            limit: 1,
            source_types: ["mark_scheme"],
            workers: 1,
          },
        }),
      );
      if (
        conversion.failed !== 0
        || conversion.succeeded + conversion.skipped !== 1
      ) {
        const backendError = conversion.errors.filter(Boolean).join("；");
        throw new Error(
          backendError
          || `Mark Scheme 转换未完成（成功 ${conversion.succeeded}，跳过 ${conversion.skipped}，失败 ${conversion.failed}）。`,
        );
      }
      const refreshedDocuments = await loadSources(true);
      if (!refreshedDocuments) return;
      const uploadedDocumentId = String(uploaded.id);
      if (!refreshedDocuments.some(
        (item) => String(item.id) === uploadedDocumentId,
      )) {
        throw new Error("上传的 Mark Scheme 转换后尚未就绪，请稍后重试。");
      }
      if (
        requestId !== uploadRequestRef.current
        || selectionRevision !== documentSelectionRevisionRef.current
        || (
          documentIdRef.current !== activeDocumentId
          && documentIdRef.current !== uploadedDocumentId
        )
      ) return;
      if (documentIdRef.current !== uploadedDocumentId) {
        chooseDocument(uploadedDocumentId);
      }
      notify("Mark Scheme 已上传并完成转换，可开始解析评分规则。");
    } catch (cause) {
      if (
        requestId === uploadRequestRef.current
        && selectionRevision === documentSelectionRevisionRef.current
        && documentIdRef.current === activeDocumentId
      ) {
        setError(cause instanceof Error ? cause.message : "Mark Scheme 上传或转换失败");
      }
    } finally {
      finishBusy(operationId);
      event.target.value = "";
    }
  }

  async function generateScheme() {
    if (!activePaper || !paperId) return;
    const activePaperId = paperId;
    const operationId = beginBusy("generate-rubric");
    setError(null);
    try {
      const created = await unwrapApi(
        apiClient.POST("/api/v1/grading/rubrics/generate", {
          headers: subjectHeaders(subjectId),
          body: { paper_job_id: activePaperId },
        }),
      );
      if (paperIdRef.current !== activePaperId || created.paper_job_id !== activePaperId) return;
      await loadSources(true);
      documentSelectionExplicitRef.current = true;
      documentIdRef.current = created.source_document_id;
      setDocumentId(created.source_document_id);
      rubricIdRef.current = created.id;
      setRubric(created);
      setRubrics((items) => [created, ...items.filter((item) => item.id !== created.id)]);
      notify("临时 AI 评分标准已生成，须逐条审核后才能评分。");
      setGenerateSchemeConfirmOpen(false);
      setRubricReviewOpen(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "AI 评分标准生成失败");
    } finally {
      finishBusy(operationId);
    }
  }

  async function createRubric() {
    if (!activePaper || !paperId || !documentId) return;
    const activePaperId = paperId;
    const activeDocumentId = documentId;
    const requestId = ++rubricCreationRequestRef.current;
    const operationId = beginBusy("create-rubric");
    setError(null);
    try {
      const created = await unwrapApi(
        apiClient.POST("/api/v1/grading/rubrics", {
          headers: subjectHeaders(subjectId),
          body: { paper_job_id: activePaperId, source_document_id: activeDocumentId },
        }),
      );
      if (
        requestId !== rubricCreationRequestRef.current
        || paperIdRef.current !== activePaperId
        || documentIdRef.current !== activeDocumentId
        || created.paper_job_id !== activePaperId
        || created.source_document_id !== activeDocumentId
      ) return;
      rubricIdRef.current = created.id;
      setRubric(created);
      setRubrics((items) => [
        created,
        ...items.filter((item) => item.id !== created.id),
      ]);
      notify("评分标准已解析，请确认每个得分点后再开始判分。");
      if (stepRef.current === 1) setRubricReviewOpen(true);
    } catch (cause) {
      if (
        requestId === rubricCreationRequestRef.current
        && paperIdRef.current === activePaperId
        && documentIdRef.current === activeDocumentId
      ) {
        setError(cause instanceof Error ? cause.message : "评分方案解析失败");
      }
    } finally {
      finishBusy(operationId);
    }
  }


  function applyRefreshedRubric(refreshed: RubricSet, expectedRubricId: string) {
    if (
      rubricIdRef.current !== expectedRubricId
      || refreshed.id !== expectedRubricId
      || refreshed.paper_job_id !== paperIdRef.current
      || refreshed.source_document_id !== documentIdRef.current
    ) return false;
    setRubric(refreshed);
    setRubrics((items) => items.map(
      (item) => item.id === refreshed.id ? { ...item, ...refreshed } : item,
    ));
    return true;
  }

  async function reviewCriterion(
    criterionId: string,
    reviewStatus: "accepted" | "rejected",
    note: string,
    updates: RubricCriterionPatch | undefined,
  ): Promise<boolean> {
    if (!activeRubric) return false;
    const reviewerName = reviewer.trim();
    if (!reviewerName) {
      setError("请先填写审核人名称。");
      return false;
    }
    const rubricId = activeRubric.id;
    const activePaperId = activeRubric.paper_job_id;
    const activeDocumentId = activeRubric.source_document_id;
    const operationId = beginBusy(`review-${criterionId}`);
    setError(null);
    try {
      const refreshed = await unwrapApi(
        apiClient.POST("/api/v1/grading/rubrics/{rubric_id}/criteria/{criterion_id}/review", {
          headers: subjectHeaders(subjectId),
          params: { path: { rubric_id: rubricId, criterion_id: criterionId } },
          body: {
            note: note.trim() || null,
            review_status: reviewStatus,
            reviewer: reviewerName,
            updates,
          },
        }),
      );
      if (!applyRefreshedRubric(refreshed, rubricId)) return false;
      window.localStorage.setItem(REVIEWER_STORAGE_KEY, reviewerName);
      notify(reviewStatus === "accepted" ? "得分规则已保留。" : "得分规则已排除。");
      return true;
    } catch (cause) {
      if (
        paperIdRef.current === activePaperId
        && documentIdRef.current === activeDocumentId
        && rubricIdRef.current === rubricId
      ) {
        setError(cause instanceof Error ? cause.message : "得分点审核失败");
      }
      return false;
    } finally {
      finishBusy(operationId);
    }
  }

  async function batchReviewCriteria(request: BatchReviewRubricCriteriaRequest): Promise<boolean> {
    if (request.decisions.length > MAX_BATCH_REVIEW_CRITERIA) {
      setError(`单次最多审核 ${MAX_BATCH_REVIEW_CRITERIA} 条得分点，请缩小选择范围后重试。`);
      return false;
    }
    if (!activeRubric || !request.reviewer.trim() || request.decisions.length === 0) return false;
    const rubricId = activeRubric.id;
    const activePaperId = activeRubric.paper_job_id;
    const activeDocumentId = activeRubric.source_document_id;
    const operationId = beginBusy("batch-review");
    setError(null);
    try {
      const refreshed = await unwrapApi(
        apiClient.POST("/api/v1/grading/rubrics/{rubric_id}/batch-review", {
          headers: subjectHeaders(subjectId),
          params: { path: { rubric_id: rubricId } },
          body: request,
        }),
      );
      if (!applyRefreshedRubric(refreshed, rubricId)) return false;
      window.localStorage.setItem(REVIEWER_STORAGE_KEY, request.reviewer);
      notify(`已批量审核 ${request.decisions.length} 条得分点，并分别写入审计记录。`);
      return true;
    } catch (cause) {
      if (
        paperIdRef.current === activePaperId
        && documentIdRef.current === activeDocumentId
        && rubricIdRef.current === rubricId
      ) {
        setError(cause instanceof Error ? cause.message : "批量审核失败");
      }
      return false;
    } finally {
      finishBusy(operationId);
    }
  }

  async function aiReviewCriteria(request: AiReviewRubricCriteriaRequest) {
    if (request.criterion_ids.length > MAX_BATCH_REVIEW_CRITERIA) {
      setError(`单次最多审核 ${MAX_BATCH_REVIEW_CRITERIA} 条得分点，请缩小选择范围后重试。`);
      return;
    }
    if (!activeRubric || request.criterion_ids.length === 0) return;
    const rubricId = activeRubric.id;
    const activePaperId = activeRubric.paper_job_id;
    const activeDocumentId = activeRubric.source_document_id;
    const operationId = beginBusy("ai-review");
    setError(null);
    try {
      const refreshed = await unwrapApi(
        apiClient.POST("/api/v1/grading/rubrics/{rubric_id}/ai-review", {
          headers: subjectHeaders(subjectId),
          params: { path: { rubric_id: rubricId } },
          body: request,
        }),
      );
      if (!applyRefreshedRubric(refreshed, rubricId)) return;
      notify(`AI 已为 ${request.criterion_ids.length} 条得分点保存检查建议；人工状态未改变。`);
    } catch (cause) {
      if (
        paperIdRef.current === activePaperId
        && documentIdRef.current === activeDocumentId
        && rubricIdRef.current === rubricId
      ) {
        setError(cause instanceof Error ? cause.message : "AI 审核失败");
      }
    } finally {
      finishBusy(operationId);
    }
  }

  async function confirmRubric() {
    if (!activePaper || !activeRubric) return;
    const reviewerName = reviewer.trim();
    if (!reviewerName) {
      setError("请先填写审核人名称。");
      return;
    }
    const rubricId = activeRubric.id;
    const activePaperId = activePaper.job_id;
    const activeDocumentId = activeRubric.source_document_id;
    const operationId = beginBusy("confirm-rubric");
    setError(null);
    try {
      const refreshed = await unwrapApi(
        apiClient.POST("/api/v1/grading/rubrics/{rubric_id}/confirm", {
          headers: subjectHeaders(subjectId),
          params: { path: { rubric_id: rubricId } },
          body: { reviewer: reviewerName },
        }),
      );
      if (!applyRefreshedRubric(refreshed, rubricId)) return;
      window.localStorage.setItem(REVIEWER_STORAGE_KEY, reviewerName);
      notify("评分规则已确认，现可对既有答案记录评分。");
      void loadOverview(activePaperId, activeDocumentId, rubricId);
      setRubricReviewOpen(false);
      transitionToStep(3, refreshed, true);
    } catch (cause) {
      if (
        paperIdRef.current === activePaperId
        && documentIdRef.current === activeDocumentId
        && rubricIdRef.current === rubricId
      ) {
        setError(cause instanceof Error ? cause.message : "评分规则确认失败");
      }
    } finally {
      finishBusy(operationId);
    }
  }

  async function assessQuestion(position: number): Promise<GradeResult | undefined> {
    if (!activePaper || !activeRubric) return;
    const activePaperId = activePaper.job_id;
    const activeDocumentId = activeRubric.source_document_id;
    const rubricId = activeRubric.id;
    const requestId = ++assessmentRequestRef.current;
    const operationId = beginBusy(`grade-${position}`);
    setError(null);
    try {
      const result = await unwrapApi(
        apiClient.POST("/api/v1/grading/papers/{paper_job_id}/questions/{position}/assess", {
          headers: subjectHeaders(subjectId),
          params: { path: { paper_job_id: activePaperId, position } },
          body: { rubric_set_id: rubricId },
        }),
      );
      if (
        requestId !== assessmentRequestRef.current
        || paperIdRef.current !== activePaperId
        || documentIdRef.current !== activeDocumentId
        || rubricIdRef.current !== rubricId
      ) return;
      const persistedAssessment: PaperAssessment = {
        id: result.assessment_id,
        paper_job_id: activePaperId,
        question_position: position,
        rubric_set_id: rubricId,
        status: result.status,
        result,
        created_at: new Date().toISOString(),
      };
      setAssessments((items) => [
        persistedAssessment,
        ...items.filter(
          (item) =>
            item.id !== persistedAssessment.id
            && !(
              item.paper_job_id === activePaperId
              && item.rubric_set_id === rubricId
              && item.question_position === position
            ),
        ),
      ]);
      notify(`Q${activePaper.questions.find((item) => item.position === position)?.number ?? position} 已完成自动初评。`);
      finishBusy(operationId);

      const reconciliationId = ++reconciliationRequestRef.current;
      void (async () => {
        const [assessmentRefresh, overviewRefresh, createdRefresh] = await Promise.allSettled([
          unwrapApi(
            apiClient.GET("/api/v1/grading/papers/{paper_job_id}/assessments", {
              headers: subjectHeaders(subjectId),
              params: { path: { paper_job_id: activePaperId } },
            }),
          ),
          unwrapApi(
            apiClient.GET("/api/v1/grading/papers/{paper_job_id}/overview", {
              headers: subjectHeaders(subjectId),
              params: {
                path: { paper_job_id: activePaperId },
                query: { rubric_set_id: rubricId },
              },
            }),
          ),
          Promise.resolve().then(onCreated),
        ]);
        if (
          reconciliationId !== reconciliationRequestRef.current
          || paperIdRef.current !== activePaperId
          || documentIdRef.current !== activeDocumentId
          || rubricIdRef.current !== rubricId
        ) return;
        if (assessmentRefresh.status === "fulfilled") {
          const refreshed = assessmentRefresh.value.filter(
            (item) => item.paper_job_id === activePaperId,
          );
          const includesPersistedResult = refreshed.some(
            (item) => item.id === persistedAssessment.id,
          );
          setAssessments(
            includesPersistedResult
              ? refreshed
              : [
                  persistedAssessment,
                  ...refreshed.filter(
                    (item) =>
                      item.rubric_set_id !== rubricId
                      || item.question_position !== position,
                  ),
                ],
          );
        } else {
          setError("评分已生成，但最新结果列表刷新失败；请重新载入页面，不要重复生成。");
        }
        if (overviewRefresh.status === "fulfilled") {
          if (
            overviewRefresh.value.paper_job_id === activePaperId
            && overviewRefresh.value.rubric_set_id === rubricId
          ) {
            overviewRequestRef.current += 1;
            setOverview(overviewRefresh.value);
            setOverviewError(null);
          } else {
            setOverviewError("评分已生成，但整卷总览与当前评分上下文不匹配；可在总览步骤安全重试刷新。");
          }
        } else {
          setOverviewError("评分已生成，但整卷总览刷新失败；可在总览步骤安全重试刷新。");
        }
        if (createdRefresh.status === "rejected") {
          setError("评分已生成，但人工复核队列刷新失败；请重新载入页面，不要重复生成。");
        }
      })();
      return result;
    } catch (cause) {
      if (
        requestId === assessmentRequestRef.current
        && paperIdRef.current === activePaperId
        && documentIdRef.current === activeDocumentId
        && rubricIdRef.current === rubricId
      ) {
        setError(cause instanceof Error ? cause.message : "自动评分失败");
      }
    } finally {
      finishBusy(operationId);
    }
  }

  const selectRubric = useCallback(async (nextRubricId: string): Promise<boolean> => {
    if (!activePaper || !documentIdRef.current) return false;
    const requestId = ++rubricRequestRef.current;
    rubricCreationRequestRef.current += 1;
    assessmentRequestRef.current += 1;
    reconciliationRequestRef.current += 1;
    overviewRequestRef.current += 1;
    setOverviewBusy(false);
    const activePaperId = activePaper.job_id;
    const activeDocumentId = documentIdRef.current;
    const operationId = beginBusy("loading-rubric");
    rubricIdRef.current = null;
    setRubric(null);
    setSelectedPosition(null);
    setError(null);
    setOverview(null);
    setOverviewError(null);
    try {
      const [detail, nextAssessments] = await Promise.all([
        unwrapApi(
          apiClient.GET("/api/v1/grading/rubrics/{rubric_id}", {
            headers: subjectHeaders(subjectId),
            params: { path: { rubric_id: nextRubricId } },
          }),
        ),
        unwrapApi(
          apiClient.GET("/api/v1/grading/papers/{paper_job_id}/assessments", {
            headers: subjectHeaders(subjectId),
            params: { path: { paper_job_id: activePaperId } },
          }),
        ),
      ]);
      if (
        requestId !== rubricRequestRef.current
        || paperIdRef.current !== activePaperId
        || documentIdRef.current !== activeDocumentId
      ) return false;
      if (
        detail.id !== nextRubricId
        || detail.paper_job_id !== activePaperId
        || detail.source_document_id !== activeDocumentId
      ) {
        setError("所选评分规则不属于当前答卷或 Mark Scheme，请重新选择。");
        return false;
      }
      rubricIdRef.current = detail.id;
      setRubric(detail);
      setAssessments(nextAssessments.filter(
        (item) =>
          item.paper_job_id === activePaperId
          && item.rubric_set_id === detail.id,
      ));
      setSelectedPosition(
        activePaper.questions.find((item) => item.status === "completed")?.position ?? null,
      );
      if (detail.status === "confirmed") {
        void loadOverview(activePaperId, activeDocumentId, detail.id);
      }
      return true;
    } catch (cause) {
      if (
        requestId === rubricRequestRef.current
        && paperIdRef.current === activePaperId
        && documentIdRef.current === activeDocumentId
      ) {
        setError(cause instanceof Error ? cause.message : "评分规则加载失败");
      }
      return false;
    } finally {
      finishBusy(operationId);
    }
  }, [activePaper, beginBusy, finishBusy, loadOverview, subjectId]);

  useLayoutEffect(() => {
    const pendingDocument = pendingDiscoveredDocumentRef.current;
    if (!pendingDocument) return;
    if (documentSelectionExplicitRef.current) {
      pendingDiscoveredDocumentRef.current = null;
      return;
    }
    if (
      pendingDocument.paperId !== paperId
      || pendingDocument.documentId !== documentId
      || !activePaper
      || activePaper.job_id !== pendingDocument.paperId
    ) return;
    pendingDiscoveredDocumentRef.current = null;
    if (activeRubric) return;
    const matchingRubric = rubrics.find(
      (item) =>
        item.paper_job_id === pendingDocument.paperId
        && item.source_document_id === pendingDocument.documentId,
    );
    if (matchingRubric) void selectRubric(matchingRubric.id);
  }, [activePaper, activeRubric, documentId, paperId, rubrics, selectRubric]);

  async function refreshOverview() {
    const activePaperId = paperIdRef.current;
    const activeDocumentId = documentIdRef.current;
    const rubricId = rubricIdRef.current;
    if (!activePaperId || !activeDocumentId || !rubricId) return;
    await loadOverview(activePaperId, activeDocumentId, rubricId);
  }

  function chooseSubject(nextSubjectId: string) {
    setSubjectId(nextSubjectId);
    setPaperId("");
    setDocumentId("");
    setPapers([]);
    setDocuments([]);
    clearPaperContextState();
    setPapersLoading(true);
    setDocumentsLoading(true);
    setStep(1);
    setRubricReviewOpen(false);
  }

  return (
    <section className="grading-page" ref={pageRef}>
      <header className="page-heading">
        <div>
          <h1>答案评分</h1>
        </div>
      </header>

      {legacyMode || routedContext ? (
        <nav aria-label="评分流程" className="grading-journey">
          <button aria-current={step === 1 ? "step" : undefined} className={step === 1 ? "current" : "completed"} disabled={journeyLocked} onClick={() => transitionToStep(1)} type="button">
            <span>01</span><strong>准备材料</strong>
          </button>
          <button aria-current={step === 3 ? "step" : undefined} className={step === 3 ? "current" : step > 3 ? "completed" : ""} disabled={journeyLocked || activeRubric?.status !== "confirmed"} onClick={() => transitionToStep(3)} type="button">
            <span>02</span><strong>逐题判分</strong>
          </button>
          <button aria-current={step === 4 ? "step" : undefined} className={step === 4 ? "current" : ""} disabled={journeyLocked || activeRubric?.status !== "confirmed"} onClick={() => { transitionToStep(4); void refreshOverview(); }} type="button">
            <span>03</span><strong>整卷结果</strong>
          </button>
        </nav>
      ) : (
        <nav aria-label="评分流程" className="grading-journey four-step">
          <button
            aria-current={!subject ? "step" : undefined}
            className={!subject ? "current" : "completed"}
            disabled={journeyLocked}
            onClick={() => setSubjectId("")}
            type="button"
          >
            <span>01</span><strong>选择科目</strong>
          </button>
          <button
            aria-current={subject && step === 1 ? "step" : undefined}
            className={subject && step === 1 ? "current" : subject && step > 1 ? "completed" : ""}
            disabled={!subject || journeyLocked}
            onClick={() => transitionToStep(1)}
            type="button"
          >
            <span>02</span><strong>准备材料</strong>
          </button>
          <button
            aria-current={step === 3 ? "step" : undefined}
            className={step === 3 ? "current" : step > 3 ? "completed" : ""}
            disabled={!subject || journeyLocked || activeRubric?.status !== "confirmed"}
            onClick={() => transitionToStep(3)}
            type="button"
          >
            <span>03</span><strong>AI 逐题评分</strong>
          </button>
          <button
            aria-current={step === 4 ? "step" : undefined}
            className={step === 4 ? "current" : ""}
            disabled={!subject || journeyLocked || activeRubric?.status !== "confirmed"}
            onClick={() => { transitionToStep(4); void refreshOverview(); }}
            type="button"
          >
            <span>04</span><strong>整卷结果</strong>
          </button>
        </nav>
      )}

      {!subject && (
        <section className="grading-subject-step" aria-labelledby="grading-subject-heading">
          <div className="grading-stage-header"><span>第 1 步</span><h2 id="grading-subject-heading">选择需要评分的科目</h2></div>
          <div className="workflow-subject-list">
            {subjects.map((item) => (
              <button key={item.id} onClick={() => chooseSubject(item.id)} type="button">
                <span><strong>{item.title}</strong><small>{item.subject_code} · {item.board_name}</small></span>
              </button>
            ))}
          </div>
        </section>
      )}

      {subject && step === 1 && (
        <GradingMaterialsStage
          busy={busy}
          documentId={documentId}
          documents={documents}
          documentsError={documentsError}
          documentsLoading={documentsLoading}
          error={error}
          onRetryDiscovery={loadDiscoveryLists}
          onChooseDocument={chooseDocument}
          onChoosePaper={choosePaper}
          onContinue={prepareRubric}
          onDeleteDocument={deleteSchemeMaterial}
          onDeletePaper={deletePaperMaterial}
          onRenameDocument={renameSchemeMaterial}
          onRenamePaper={renamePaperMaterial}
          onUploadScheme={uploadScheme}
          onGenerateScheme={async () => setGenerateSchemeConfirmOpen(true)}
          paper={activePaper}
          paperId={paperId}
          papers={papers}
          onImportExternal={importExternalAnswer}
          importJob={importJob}
          importStreamState={importStreamState}
          onReconnectImport={() => setImportStreamVersion((version) => version + 1)}
          sourceBookletRequired={subject.source_booklet_required}
          papersError={papersError}
          papersLoading={papersLoading}
          rubric={activeRubric}
        />
      )}
      {subject && rubricReviewOpen && (
        <AppDialog
          contentClassName="rubric-review-modal-shell"
          dismissible={!rubricWritePending}
          initialFocusSelector="#grading-stage-2-heading"
          onOpenChange={(open) => {
            if (!open) closeRubricReview();
          }}
          open
          title="审核评分标准"
        >
            <RubricReviewStage
              busy={busy}
              error={error}
              onAiReview={aiReviewCriteria}
              onBack={closeRubricReview}
              onBatchReview={batchReviewCriteria}
              onConfirmRubric={confirmRubric}
              onNext={() => {
                setRubricReviewOpen(false);
                transitionToStep(3);
              }}
              onReviewCriterion={reviewCriterion}
              onReviewerChange={setReviewer}
              onSelectRubric={async (nextRubricId) => {
                await selectRubric(nextRubricId);
              }}
              reviewer={reviewer}
              rubric={activeRubric}
              rubrics={activePaper
                ? rubrics.filter(
                    (item) =>
                      item.paper_job_id === paperId
                      && item.source_document_id === documentId,
                  )
                : []}
            />
        </AppDialog>
      )}
      <AppConfirmDialog
        busy={busy === "generate-rubric"}
        confirmLabel="生成临时评分标准"
        description="仅在没有官方 Mark Scheme 时使用。生成结果会标记为 AI 草案，必须由教师逐条审核并确认后才能评分。"
        onConfirm={generateScheme}
        onOpenChange={setGenerateSchemeConfirmOpen}
        open={generateSchemeConfirmOpen}
        title="使用 AI 生成评分标准？"
      />
      {subject && step === 3 && (
        <GradingQuestionStage
          assessments={activeAssessments}
          busy={busy}
          error={error}
          onAssessQuestion={assessQuestion}
          onBack={() => transitionToStep(1)}
          onViewRubric={() => setRubricReviewOpen(true)}
          onOverview={() => {
            transitionToStep(4);
            void refreshOverview();
          }}
          onSelectPosition={setSelectedPosition}
          paper={activePaper}
          rubric={activeRubric}
          selectedPosition={selectedPosition}
          subjectId={subject.id}
        />
      )}
      {subject && step === 4 && (
        <GradingOverview
          error={overviewError}
          loading={overviewBusy}
          onBack={() => transitionToStep(3)}
          onRefresh={refreshOverview}
          overview={overview}
        />
      )}
    </section>
  );
}
