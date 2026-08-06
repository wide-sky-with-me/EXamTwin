import {
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  FileCheck2,
  GraduationCap,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  UploadCloud,
} from "lucide-react";
import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AnswerDiagramView } from "../components/AnswerDiagramView";
import { AnswerImageView } from "../components/AnswerImageView";
import { Markdown, QuestionMarkdown } from "../components/Markdown";
import { Confidence, ErrorBanner } from "../components/Feedback";
import { useToast } from "../components/toast-context";
import { apiClient, unwrapApi, uploadWorkspaceDocument } from "../lib/api";
import type {
  GradeResult,
  GradingPaper,
  PaperAssessment,
  PaperJobQuestion,
  PaperJobResult,
  RubricSet,
  RubricSetSummary,
  SourceDocument,
  SubjectPack,
} from "../types";
type GradingStep = 1 | 2 | 3;


function GradingSubmission({
  jobId,
  question,
}: {
  jobId: string;
  question: PaperJobQuestion;
}) {
  return (
    <div className="grading-submission">
      <section>
        <h3>原题</h3>
        <div className="grading-rich grading-question">
          <QuestionMarkdown>{question.question_markdown}</QuestionMarkdown>
        </div>
      </section>
      <section>
        <h3>已保存答案</h3>
        <div className="grading-rich">
          <Markdown>{question.answer_markdown}</Markdown>
        </div>
        {question.diagrams.length > 0 && (
          <div className="answer-diagrams">
            {question.diagrams.map((diagram, index) => (
              <AnswerDiagramView
                diagram={diagram}
                jobId={jobId}
                key={`${diagram.title}-${index}`}
              />
            ))}
          </div>
        )}
        {question.images.length > 0 && (
          <div className="answer-diagrams">
            {question.images.map((image, index) => (
              <AnswerImageView image={image} key={`${image.content_url}-${index}`} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export function Grading({
  subject,
  onCreated,
}: {
  subject: SubjectPack;
  onCreated: () => Promise<void>;
}) {
  const [papers, setPapers] = useState<GradingPaper[]>([]);
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [paperId, setPaperId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [paper, setPaper] = useState<PaperJobResult | null>(null);
  const [rubrics, setRubrics] = useState<RubricSetSummary[]>([]);
  const [rubric, setRubric] = useState<RubricSet | null>(null);
  const [assessments, setAssessments] = useState<PaperAssessment[]>([]);
  const [selectedPosition, setSelectedPosition] = useState<number | null>(null);
  const [step, setStep] = useState<GradingStep>(1);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const paperRequestRef = useRef(0);
  const { notify } = useToast();

  const loadSources = useCallback(async () => {
    const rows = await unwrapApi(
      apiClient.GET("/api/v1/corpus/documents", {
        params: { query: { source_type: "mark_scheme", status: "converted", limit: 100 } },
      }),
    );
    setDocuments(rows as SourceDocument[]);
    if (!documentId && rows.length) setDocumentId(String(rows[0].id));
  }, [documentId]);

  const loadPapers = useCallback(async () => {
    const rows = await unwrapApi(apiClient.GET("/api/v1/grading/papers"));
    setPapers(rows);
    if (!paperId && rows.length) setPaperId(rows[0].job_id);
  }, [paperId]);
  async function loadPaperContext(nextPaperId: string) {
    const requestId = ++paperRequestRef.current;
    if (!nextPaperId) {
      setPaper(null);
      setRubrics([]);
      setRubric(null);
      setAssessments([]);
      setSelectedPosition(null);
      setBusy(null);
      setError(null);
      return;
    }
    setBusy("loading-paper");
    setError(null);
    try {
      const [nextPaper, nextRubrics, nextAssessments] = await Promise.all([
        unwrapApi(
          apiClient.GET("/api/v1/papers/jobs/{job_id}", {
            params: { path: { job_id: nextPaperId } },
          }),
        ),
        unwrapApi(
          apiClient.GET("/api/v1/grading/rubrics", {
            params: { query: { paper_job_id: nextPaperId } },
          }),
        ),
        unwrapApi(
          apiClient.GET("/api/v1/grading/papers/{paper_job_id}/assessments", {
            params: { path: { paper_job_id: nextPaperId } },
          }),
        ),
      ]);
      const nextRubric = nextRubrics.length
        ? await unwrapApi(
            apiClient.GET("/api/v1/grading/rubrics/{rubric_id}", {
              params: { path: { rubric_id: nextRubrics[0].id } },
            }),
          )
        : null;
      if (requestId !== paperRequestRef.current) return;
      setPaper(nextPaper as PaperJobResult);
      setRubrics(nextRubrics);
      setAssessments(nextAssessments);
      setSelectedPosition(
        nextPaper.questions.find((item) => item.status === "completed")?.position ?? null,
      );
      setRubric(nextRubric);
    } catch (cause) {
      if (requestId !== paperRequestRef.current) return;
      setError(cause instanceof Error ? cause.message : "评分工作区加载失败");
    } finally {
      if (requestId === paperRequestRef.current) setBusy(null);
    }
  }

  useEffect(() => {
    void Promise.all([loadPapers(), loadSources()]).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : "评分工作区加载失败");
    });
  }, [loadPapers, loadSources]);

  useEffect(() => {
    void loadPaperContext(paperId);
    return () => {
      paperRequestRef.current += 1;
    };
  }, [paperId]);

  const latestByPosition = useMemo(() => {
    const map = new Map<number, PaperAssessment>();
    if (!rubric) return map;
    for (const item of assessments) {
      if (item.rubric_set_id !== rubric.id) continue;
      if (!map.has(item.question_position)) map.set(item.question_position, item);
    }
    return map;
  }, [assessments, rubric]);
  const selectedQuestion = paper?.questions.find((item) => item.position === selectedPosition) ?? null;
  const selectedAssessment = selectedPosition == null ? null : latestByPosition.get(selectedPosition) ?? null;
  const selectedResult: GradeResult | null = selectedAssessment?.result ?? null;
  const selectedAcceptedCriteria = selectedQuestion && rubric
    ? rubric.criteria.filter(
        (item) =>
          item.review_status === "accepted"
          && item.question_number === selectedQuestion.number,
      ).length
    : 0;
  const acceptedCriteria = rubric?.criteria.filter((item) => item.review_status === "accepted").length ?? 0;
  const pendingCriteria = rubric?.criteria.filter((item) => item.review_status === "pending").length ?? 0;
  const selectedPaperSummary = papers.find((item) => item.job_id === paperId) ?? null;
  const selectedDocument = documents.find((item) => item.id === documentId) ?? null;

  function choosePaper(nextPaperId: string) {
    paperRequestRef.current += 1;
    setPaperId(nextPaperId);
    setStep(1);
  }

  function chooseDocument(nextDocumentId: string) {
    setDocumentId(nextDocumentId);
    setStep(1);
  }

  async function prepareRubric() {
    if (
      rubric
      && rubric.paper_job_id === paperId
      && rubric.source_document_id === documentId
    ) {
      setStep(2);
      return;
    }
    await createRubric();
  }


  async function uploadScheme(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy("upload");
    setError(null);
    try {
      const uploaded = await uploadWorkspaceDocument(subject.id, file, "mark_scheme");
      await unwrapApi(
        apiClient.POST("/api/v1/corpus/convert", {
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
      await loadSources();
      setDocumentId(uploaded.id);
      setStep(1);
      notify("Mark Scheme 已上传并完成转换，可开始解析评分规则。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Mark Scheme 上传或转换失败");
    } finally {
      setBusy(null);
      event.target.value = "";
    }
  }

  async function createRubric() {
    if (!paperId || !documentId) return;
    setBusy("create-rubric");
    setError(null);
    try {
      const created = await unwrapApi(
        apiClient.POST("/api/v1/grading/rubrics", {
          body: { paper_job_id: paperId, source_document_id: documentId },
        }),
      );
      setRubric(created);
      await loadPaperContext(paperId);
      notify("评分方案已解析为可审核的原子规则。");
      setStep(2);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "评分方案解析失败");
    } finally {
      setBusy(null);
    }
  }

  async function reviewAndConfirm() {
    if (!rubric) return;
    setBusy("confirm-rubric");
    setError(null);
    try {
      const reviewed = await unwrapApi(
        apiClient.POST("/api/v1/grading/rubrics/{rubric_id}/review-all", {
          params: { path: { rubric_id: rubric.id } },
          body: { review_status: "accepted" },
        }),
      );
      const confirmed = await unwrapApi(
        apiClient.POST("/api/v1/grading/rubrics/{rubric_id}/confirm", {
          params: { path: { rubric_id: reviewed.id } },
        }),
      );
      setRubric(confirmed);
      notify("评分规则已确认，现可对既有答案记录评分。");
      setStep(3);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "评分规则确认失败");
    } finally {
      setBusy(null);
    }
  }

  async function assessQuestion(position: number) {
    if (!paper || !rubric) return;
    setBusy(`grade-${position}`);
    setError(null);
    try {
      const result = await unwrapApi(
        apiClient.POST("/api/v1/grading/papers/{paper_job_id}/questions/{position}/assess", {
          params: { path: { paper_job_id: paper.job_id, position } },
          body: { rubric_set_id: rubric.id },
        }),
      );
      const nextAssessments = await unwrapApi(
        apiClient.GET("/api/v1/grading/papers/{paper_job_id}/assessments", {
          params: { path: { paper_job_id: paper.job_id } },
        }),
      );
      setAssessments(nextAssessments);
      setSelectedPosition(position);
      notify(`Q${paper.questions.find((item) => item.position === position)?.number ?? position} 已完成自动初评。`);
      await onCreated();
      return result;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "自动评分失败");
    } finally {
      setBusy(null);
    }
  }

  async function selectRubric(rubricId: string) {
    setBusy("loading-rubric");
    try {
      const detail = await unwrapApi(
        apiClient.GET("/api/v1/grading/rubrics/{rubric_id}", {
          params: { path: { rubric_id: rubricId } },
        }),
      );
      setRubric(detail);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "评分规则加载失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <div className="page-heading compact">
        <div>
          <h1>自动评分工作台</h1>
          <p>按顺序准备答卷、核对官方得分点，再生成逐题评分建议。</p>
        </div>
      </div>

      <nav aria-label="评分流程" className="grading-journey">
        <button
          aria-current={step === 1 ? "step" : undefined}
          className={step === 1 ? "current" : "completed"}
          onClick={() => setStep(1)}
          type="button"
        >
          <span>01</span>
          <strong>准备材料</strong>
          <small>答卷与评分标准</small>
        </button>
        <button
          aria-current={step === 2 ? "step" : undefined}
          className={step === 2 ? "current" : step > 2 ? "completed" : ""}
          disabled={!rubric}
          onClick={() => setStep(2)}
          type="button"
        >
          <span>02</span>
          <strong>核对得分点</strong>
          <small>解析并人工确认</small>
        </button>
        <button
          aria-current={step === 3 ? "step" : undefined}
          className={step === 3 ? "current" : ""}
          disabled={rubric?.status !== "confirmed"}
          onClick={() => setStep(3)}
          type="button"
        >
          <span>03</span>
          <strong>评分建议</strong>
          <small>逐题生成与复核</small>
        </button>
      </nav>

      {step === 1 && (
        <article className="panel grading-stage">
          <header className="grading-stage-header">
            <div>
              <span>步骤 1 · 材料准备</span>
              <h2>先确认本次评分使用的两份材料</h2>
              <p>答卷来自已完成的整卷作答；Mark Scheme 必须是对应试卷的官方版本。</p>
            </div>
          </header>

          <div className="grading-source-cards">
            <section className="grading-source-card">
              <div className="grading-source-heading">
                <span>A</span>
                <div>
                  <strong>已完成作答</strong>
                  <small>选择需要评分的答卷记录</small>
                </div>
              </div>
              <select
                aria-label="选择作答记录"
                onChange={(event) => choosePaper(event.target.value)}
                value={paperId}
              >
                <option value="">暂无可评分试卷</option>
                {papers.map((item) => (
                  <option key={item.job_id} value={item.job_id}>
                    {item.filename} · {item.completed_questions}/{item.total_questions} 题
                  </option>
                ))}
              </select>
              {selectedPaperSummary && (
                <div className="grading-source-summary">
                  <FileCheck2 size={19} />
                  <div>
                    <strong>{selectedPaperSummary.filename}</strong>
                    <span>
                      {selectedPaperSummary.completed_questions} / {selectedPaperSummary.total_questions}
                      {" "}题已有答案
                      {selectedPaperSummary.failed_questions
                        ? ` · ${selectedPaperSummary.failed_questions} 题需处理`
                        : " · 作答完整"}
                    </span>
                  </div>
                </div>
              )}
              {paper && (
                <div className="grading-question-sample" aria-label="所选答卷内容">
                  {paper.questions.slice(0, 4).map((item) => (
                    <span key={item.position}>
                      <b>Q{item.number}</b>
                      {item.status === "completed" ? "答案已保存" : "暂无完整答案"}
                    </span>
                  ))}
                  {paper.questions.length > 4 && <small>另有 {paper.questions.length - 4} 题</small>}
                </div>
              )}
            </section>

            <section className="grading-source-card">
              <div className="grading-source-heading">
                <span>B</span>
                <div>
                  <strong>官方 Mark Scheme</strong>
                  <small>选择已转换版本，或上传新文件</small>
                </div>
              </div>
              <div className="scheme-picker">
                <select
                  aria-label="选择 Mark Scheme"
                  onChange={(event) => chooseDocument(event.target.value)}
                  value={documentId}
                >
                  <option value="">请选择评分方案</option>
                  {documents.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.filename} · {item.status}
                    </option>
                  ))}
                </select>
                <label className="secondary file-button">
                  {busy === "upload"
                    ? <LoaderCircle className="spin" size={15} />
                    : <UploadCloud size={15} />}
                  上传
                  <input
                    accept=".pdf,.md,.markdown"
                    disabled={busy !== null}
                    onChange={uploadScheme}
                    type="file"
                  />
                </label>
              </div>
              {selectedDocument && (
                <div className="grading-source-summary">
                  <BookOpenCheck size={19} />
                  <div>
                    <strong>{selectedDocument.filename}</strong>
                    <span>
                      {selectedDocument.status === "converted" ? "已转换，可解析得分点" : selectedDocument.status}
                      {selectedDocument.page_count ? ` · ${selectedDocument.page_count} 页` : ""}
                    </span>
                  </div>
                </div>
              )}
            </section>
          </div>

          <ErrorBanner message={error} />
          <footer className="grading-stage-actions">
            <small>下一步不会立即评分；你可以先核对解析出的每个得分点。</small>
            <button
              className="primary"
              disabled={!paperId || !documentId || busy !== null}
              onClick={() => void prepareRubric()}
              type="button"
            >
              {busy === "create-rubric"
                ? <LoaderCircle className="spin" size={17} />
                : <ArrowRight size={17} />}
              {rubric?.paper_job_id === paperId && rubric.source_document_id === documentId
                ? "查看已解析得分点"
                : "解析得分点"}
            </button>
          </footer>
        </article>
      )}

      {step === 2 && (
        <article className="panel grading-stage rubric-review">
          <header className="grading-stage-header">
            <button className="stage-back" onClick={() => setStep(1)} type="button">
              <ArrowLeft size={16} />
              返回材料选择
            </button>
            <div>
              <span>步骤 2 · 评分标准</span>
              <h2>核对解析出的得分点</h2>
              <p>确认题号、分值和判分描述后，才会开放逐题评分。</p>
            </div>
            {rubric && (
              <b className={`status-pill ${rubric.status}`}>
                {rubric.status === "confirmed" ? "已确认" : "待审核"}
              </b>
            )}
          </header>

          {rubrics.length > 1 && (
            <label className="rubric-version-picker">
              <span>评分规则版本</span>
              <select
                aria-label="选择评分规则版本"
                onChange={(event) => void selectRubric(event.target.value)}
                value={rubric?.id ?? ""}
              >
                {rubrics.map((item) => (
                  <option key={item.id} value={item.id}>
                    版本 {item.version_number} · {item.status}
                  </option>
                ))}
              </select>
            </label>
          )}

          {!rubric ? (
            <div className="empty compact-empty">
              <BookOpenCheck size={30} />
              <p>返回上一步选择材料并解析得分点。</p>
            </div>
          ) : (
            <>
              <div className="rubric-stats">
                <span><b>{rubric.criteria.length}</b> 条规则</span>
                <span><b>{acceptedCriteria}</b> 已接受</span>
                <span><b>{pendingCriteria}</b> 待审核</span>
              </div>
              {rubric.warnings.map((warning) => (
                <p className="inline-warning" key={warning}>
                  <TriangleAlert size={14} />
                  {warning}
                </p>
              ))}
              <div className="rubric-preview rubric-preview-full">
                {rubric.criteria.map((item) => (
                  <div key={item.id}>
                    <span>Q{item.question_number} · {item.mark_type ?? item.scoring_mode}</span>
                    <b>{item.max_marks}</b>
                    <div className="rubric-preview-description">
                      <Markdown>{item.description}</Markdown>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          <ErrorBanner message={error} />
          <footer className="grading-stage-actions">
            <button className="secondary" onClick={() => setStep(1)} type="button">
              <ArrowLeft size={16} />
              上一步
            </button>
            {rubric?.status === "draft" ? (
              <button
                className="primary"
                disabled={busy !== null}
                onClick={() => void reviewAndConfirm()}
                type="button"
              >
                {busy === "confirm-rubric"
                  ? <LoaderCircle className="spin" size={17} />
                  : <CheckCircle2 size={17} />}
                接受全部并进入评分
              </button>
            ) : (
              <button
                className="primary"
                disabled={!rubric}
                onClick={() => setStep(3)}
                type="button"
              >
                进入逐题评分建议
                <ArrowRight size={17} />
              </button>
            )}
          </footer>
        </article>
      )}

      {step === 3 && (
        <div className="grading-stage-three">
          <header className="grading-stage-header grading-stage-three-header">
            <button className="stage-back" onClick={() => setStep(2)} type="button">
              <ArrowLeft size={16} />
              返回得分点
            </button>
            <div>
              <span>步骤 3 · 逐题评分</span>
              <h2>生成并复核评分建议</h2>
              <p>每题独立评分；所有结果仍需进入人工复核。</p>
            </div>
          </header>
          <ErrorBanner message={error} />

          <div className="grading-paper-workspace">
            <nav className="panel grading-question-nav" aria-label="可评分题目">
              <div className="panel-title">
                <div>
                  <span>作答记录</span>
                  <h2>{paper?.filename ?? "未选择试卷"}</h2>
                </div>
              </div>
              {paper?.questions.map((item) => {
                const assessment = latestByPosition.get(item.position);
                return (
                  <button
                    className={selectedPosition === item.position ? "active" : ""}
                    key={item.position}
                    onClick={() => setSelectedPosition(item.position)}
                    type="button"
                  >
                    <span>
                      <b>Q{item.number}</b>
                      <small>{item.status === "completed" ? "答案已保存" : "暂无完整答案"}</small>
                    </span>
                    {assessment
                      ? <em>{assessment.result.total_awarded}/{assessment.result.total_available}</em>
                      : <i />}
                  </button>
                );
              })}
            </nav>

            <article className="panel grading-report">
              {!selectedQuestion ? (
                <div className="empty">
                  <GraduationCap size={34} />
                  <p>选择一道已有答案的题目。</p>
                </div>
              ) : !selectedResult ? (
                <div className="grade-ready">
                  <div>
                    <span>Q{selectedQuestion.number}</span>
                    <h2>生成本题评分建议</h2>
                  </div>
                  <GradingSubmission jobId={paper!.job_id} question={selectedQuestion} />
                  {selectedAcceptedCriteria === 0 && (
                    <p className="inline-warning">
                      <TriangleAlert size={14} />
                      当前评分标准没有匹配 Q{selectedQuestion.number} 的已接受得分点。
                    </p>
                  )}
                  <button
                    className="primary"
                    disabled={
                      rubric?.status !== "confirmed"
                      || selectedQuestion.status !== "completed"
                      || selectedAcceptedCriteria === 0
                      || busy !== null
                    }
                    onClick={() => void assessQuestion(selectedQuestion.position)}
                    type="button"
                  >
                    {busy === `grade-${selectedQuestion.position}`
                      ? <LoaderCircle className="spin" size={18} />
                      : <GraduationCap size={18} />}
                    生成评分建议
                  </button>
                </div>
              ) : (
                <>
                  <div className="score-hero">
                    <div>
                      <strong>{selectedResult.total_awarded}</strong>
                      <span>/ {selectedResult.total_available}</span>
                    </div>
                    <p>等待人工复核</p>
                  </div>
                  <GradingSubmission jobId={paper!.job_id} question={selectedQuestion} />
                  <div className="grading-assurance">
                    <span>模型置信度 <Confidence value={selectedResult.confidence} /></span>
                    <span>{selectedResult.rubric_awards.length} 个评分原子</span>
                    <span>{selectedResult.symbolic_checks.length} 项独立检查</span>
                  </div>
                  {selectedResult.warnings.map((warning) => (
                    <p className="inline-warning" key={warning}>
                      <TriangleAlert size={14} />
                      {warning}
                    </p>
                  ))}
                  <div className="rubric-list">
                    {selectedResult.rubric_awards.map((item) => (
                      <div className="rubric" key={item.criterion_id}>
                        <div className="rubric-heading">
                          <span>{item.mark_type ?? item.criterion_id}</span>
                          <b>{item.awarded}/{item.max_marks}</b>
                        </div>
                        <div className="rubric-rich rubric-description">
                          <Markdown>{item.description}</Markdown>
                        </div>
                        <div className="rubric-rich rubric-rationale">
                          <Markdown>{item.rationale}</Markdown>
                        </div>
                        {item.student_evidence && (
                          <blockquote><Markdown>{item.student_evidence}</Markdown></blockquote>
                        )}
                        {item.error_types.length > 0 && (
                          <div className="error-tags">
                            {item.error_types.map((type) => <span key={type}>{type}</span>)}
                          </div>
                        )}
                        {item.improvement_suggestion && (
                          <div className="improvement">
                            <span>改进：</span>
                            <Markdown>{item.improvement_suggestion}</Markdown>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                  {selectedResult.improvement_suggestions.length > 0 && (
                    <section className="improvement-summary">
                      <h3>针对性改进建议</h3>
                      {selectedResult.improvement_suggestions.map((item) => (
                        <div className="rubric-rich" key={item}>
                          <Markdown>{item}</Markdown>
                        </div>
                      ))}
                    </section>
                  )}
                  <div className="review-required">
                    <ShieldCheck size={18} />
                    评分建议已进入人工复核队列
                  </div>
                  <button
                    className="secondary"
                    disabled={busy !== null}
                    onClick={() => void assessQuestion(selectedQuestion.position)}
                    type="button"
                  >
                    <RefreshCw size={15} />
                    重新生成建议
                  </button>
                </>
              )}
            </article>
          </div>
        </div>
      )}
    </section>
  );
}
