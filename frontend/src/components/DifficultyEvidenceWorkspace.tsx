import {
  Alert, Badge, Button, Card, Descriptions, Empty, Flex, Input, List, Modal,
  Select, Space, Statistic, Tag, Typography,
} from "antd";
import { Check, RefreshCw, Send, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createDifficultyEvidenceRun,
  getDifficultyEvidenceRun,
  listDifficultyEvidenceRuns,
  publishDifficultyEvidenceRun,
  reviewDifficultyEvidenceCandidate,
} from "../lib/api";
import type {
  DifficultyReviewRequest,
  DifficultyRunDetail,
  DifficultyRunSummary,
} from "../lib/api";
import { ErrorBanner } from "./Feedback";

const { Paragraph, Text } = Typography;
type Candidate = DifficultyRunDetail["candidates"][number];

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

function statusLabel(status: string): string {
  if (status === "published") return "已发布";
  if (status === "review_ready") return "待审核";
  if (status === "failed") return "失败";
  return status;
}

export function DifficultyEvidenceWorkspace({ subjectId }: { subjectId: string }) {
  const [runs, setRuns] = useState<DifficultyRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const selectedRunIdRef = useRef<string | null>(null);
  const [run, setRun] = useState<DifficultyRunDetail | null>(null);
  const [sourceDocumentId, setSourceDocumentId] = useState("");
  const [rejecting, setRejecting] = useState<Candidate | null>(null);
  const [rejectionNotes, setRejectionNotes] = useState("");
  const [editing, setEditing] = useState<Candidate | null>(null);
  const [editQuestion, setEditQuestion] = useState("");
  const [editPage, setEditPage] = useState(1);
  const [editQuote, setEditQuote] = useState("");
  const [editMetricName, setEditMetricName] = useState("");
  const [editMetricText, setEditMetricText] = useState("");
  const [editMetricValue, setEditMetricValue] = useState("");
  const [editMetricScale, setEditMetricScale] = useState<"percent" | "proportion">("percent");
  const [editMetricDirection, setEditMetricDirection] = useState<"success" | "difficulty">("success");
  const [editMetricComparator, setEditMetricComparator] = useState<"eq" | "approx" | "gt" | "gte" | "lt" | "lte">("eq");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRun = useCallback(async (runId: string) => {
    const detail = await getDifficultyEvidenceRun(subjectId, runId);
    setRun(detail);
    selectedRunIdRef.current = detail.id;
    setSelectedRunId(detail.id);
  }, [subjectId]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextRuns = await listDifficultyEvidenceRuns(subjectId);
      setRuns(nextRuns);
      const currentRunId = selectedRunIdRef.current;
      const nextRunId = currentRunId && nextRuns.some((item) => item.id === currentRunId)
        ? currentRunId
        : nextRuns[0]?.id ?? null;
      if (nextRunId) await loadRun(nextRunId);
      else {
        selectedRunIdRef.current = null;
        setSelectedRunId(null);
        setRun(null);
      }
    } catch (cause) {
      setError(errorMessage(cause, "难度证据加载失败"));
    } finally {
      setLoading(false);
    }
  }, [loadRun, subjectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const counts = useMemo(() => {
    const result = { total: 0, pending: 0, accepted: 0, rejected: 0, quantitative: 0 };
    for (const candidate of run?.candidates ?? []) {
      result.total += 1;
      if (!candidate.review_decision) result.pending += 1;
      else result[candidate.review_decision] += 1;
      if (candidate.evidence_level === "A") result.quantitative += 1;
    }
    return result;
  }, [run]);

  async function review(
    candidate: Candidate,
    decision: "accepted" | "rejected",
    notes?: string,
    replacement?: DifficultyReviewRequest["replacement"],
  ) {
    if (!run) return;
    setBusy(candidate.id);
    setError(null);
    try {
      const updated = await reviewDifficultyEvidenceCandidate(subjectId, run.id, candidate.id, {
        decision,
        expected_candidate_fingerprint: candidate.candidate_fingerprint,
        notes: notes?.trim() || null,
        replacement: replacement ?? null,
      });
      setRun(updated);
      setRejecting(null);
      setRejectionNotes("");
      setEditing(null);
    } catch (cause) {
      setError(errorMessage(cause, "审核提交失败"));
    } finally {
      setBusy(null);
    }
  }

  async function publish() {
    if (!run) return;
    setBusy("publish");
    setError(null);
    try {
      const updated = await publishDifficultyEvidenceRun(
        subjectId, run.id, run.run_fingerprint,
      );
      setRun(updated);
      setRuns((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (cause) {
      setError(errorMessage(cause, "难度证据发布失败"));
    } finally {
      setBusy(null);
    }
  }

  async function createRun() {
    if (!sourceDocumentId.trim()) return;
    setBusy("create");
    setError(null);
    try {
      const created = await createDifficultyEvidenceRun(subjectId, sourceDocumentId.trim());
      setRun(created);
      selectedRunIdRef.current = created.id;
      setSelectedRunId(created.id);
      setRuns((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setSourceDocumentId("");
    } catch (cause) {
      setError(errorMessage(cause, "证据批次生成失败"));
    } finally {
      setBusy(null);
    }
  }

  if (!loading && !runs.length) {
    return (
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <ErrorBanner message={error} />
        <Empty description="尚无可审核的考官报告难度证据">
          <Paragraph type="secondary">
            需要先重新发现并转换当前科目的官方 Examiner Report，并与同一考试身份的 Question Paper 严格配对后生成候选。
          </Paragraph>
          <Space.Compact style={{ width: "100%" }}>
            <Input aria-label="Examiner Report 文档 ID" onChange={(event) => setSourceDocumentId(event.target.value)} placeholder="输入已发现的 Examiner Report 文档 ID" value={sourceDocumentId} />
            <Button disabled={!sourceDocumentId.trim()} loading={busy === "create"} onClick={() => void createRun()} type="primary">生成候选</Button>
          </Space.Compact>
          <Button icon={<RefreshCw size={16} />} onClick={() => void refresh()}>刷新</Button>
        </Empty>
      </Space>
    );
  }

  const publishDisabled = !run || run.status === "published" || counts.pending > 0
    || counts.accepted === 0;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <ErrorBanner message={error} />
      <Alert
        message="候选证据不会自动进入正式难度数据"
        description="A 级仅保留报告中的官方量化指标；B 级保持定性且不生成数值。全部候选需人工审核，发布时会再次校验冻结的报告与试卷校验和。"
        showIcon
        type="info"
      />
      <Flex align="end" gap="middle" justify="space-between" wrap>
        <Select
          aria-label="证据批次"
          loading={loading}
          onChange={(value) => void loadRun(value).catch((cause) => setError(errorMessage(cause, "批次加载失败")))}
          options={runs.map((item) => ({
            label: [item.pair_key, statusLabel(item.status), item.candidate_count + " 条"].join(" · "),
            value: item.id,
          }))}
          style={{ minWidth: 320 }}
          value={selectedRunId}
        />
        <Space.Compact style={{ minWidth: 420 }}>
          <Input aria-label="Examiner Report 文档 ID" onChange={(event) => setSourceDocumentId(event.target.value)} placeholder="Examiner Report 文档 ID" value={sourceDocumentId} />
          <Button disabled={!sourceDocumentId.trim()} loading={busy === "create"} onClick={() => void createRun()}>生成候选</Button>
        </Space.Compact>
        <Button icon={<RefreshCw size={16} />} loading={loading} onClick={() => void refresh()}>刷新</Button>
      </Flex>

      {run ? (
        <>
          <Flex gap="middle" wrap>
            <Card size="small"><Statistic title="候选" value={counts.total} /></Card>
            <Card size="small"><Statistic title="待审核" value={counts.pending} /></Card>
            <Card size="small"><Statistic title="已接受" value={counts.accepted} /></Card>
            <Card size="small"><Statistic title="A级量化" value={counts.quantitative} /></Card>
          </Flex>
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="考试配对">{run.pair_key}</Descriptions.Item>
            <Descriptions.Item label="状态"><Tag>{statusLabel(run.status)}</Tag></Descriptions.Item>
            <Descriptions.Item label="报告文档"><Text code>{run.source_document_id}</Text></Descriptions.Item>
            <Descriptions.Item label="报告 SHA-256"><Text code copyable>{run.source_checksum}</Text></Descriptions.Item>
            <Descriptions.Item label="Question Paper"><Text code>{run.question_paper_document_id}</Text></Descriptions.Item>
            <Descriptions.Item label="试卷 SHA-256"><Text code copyable>{run.question_paper_checksum}</Text></Descriptions.Item>
            <Descriptions.Item label="题号目录哈希"><Text code copyable>{run.question_catalog_hash}</Text></Descriptions.Item>
            <Descriptions.Item label="科目包摘要"><Text code copyable>{run.package_digest}</Text></Descriptions.Item>
            <Descriptions.Item label="提示词摘要"><Text code copyable>{run.prompt_digest}</Text></Descriptions.Item>
            <Descriptions.Item label="提取器">{run.extractor_version} · {run.model_name}</Descriptions.Item>
          </Descriptions>
          <List
            dataSource={run.candidates}
            loading={loading}
            locale={{ emptyText: "该批次没有候选" }}
            renderItem={(candidate) => (
              <List.Item key={candidate.id}>
                <Card
                  size="small"
                  style={{ width: "100%" }}
                  title={(
                    <Flex align="center" gap="small" wrap>
                      <Text strong>Question {candidate.question_number}</Text>
                      <Tag color={candidate.evidence_level === "A" ? "blue" : "default"}>
                        {candidate.evidence_level}级 · {candidate.evidence_type === "quantitative" ? "量化" : "定性"}
                      </Tag>
                      {candidate.review_decision ? (
                        <Badge
                          status={candidate.review_decision === "accepted" ? "success" : "error"}
                          text={candidate.review_decision === "accepted" ? "已接受" : "已拒绝"}
                        />
                      ) : <Badge status="processing" text="待审核" />}
                    </Flex>
                  )}
                >
                  <Space orientation="vertical" size="small" style={{ width: "100%" }}>
                    <blockquote style={{ borderInlineStart: "3px solid #91caff", margin: 0, paddingInlineStart: 12 }}>
                      {candidate.quote}
                    </blockquote>
                    {candidate.evidence_level === "A" ? (
                      <Text>
                        官方指标：{candidate.metric_name} · {candidate.metric_comparator} · {candidate.metric_text} · 难度投影 {candidate.difficulty_score === null ? "不生成（近似值/边界值）" : candidate.difficulty_score.toFixed(3)}
                      </Text>
                    ) : <Text type="secondary">定性证据：不生成数值难度分数</Text>}
                    <Text type="secondary">
                      来源：第 {candidate.page_number} 页 · <Text code>{candidate.source_ref}</Text> · 引文 <Text code>{candidate.quote_hash.slice(0, 12)}</Text> · 页面块 <Text code>{candidate.block_hash.slice(0, 12)}</Text>
                    </Text>
                    {candidate.validation_errors.length ? (
                      <Alert message={candidate.validation_errors.join("；")} showIcon type="error" />
                    ) : null}
                    {run.status !== "published" ? (
                      <Flex gap="small" justify="flex-end">
                        <Button
                          onClick={() => {
                            setEditing(candidate);
                            setEditQuestion(candidate.question_number);
                            setEditPage(candidate.page_number);
                            setEditQuote(candidate.quote);
                            setEditMetricName(candidate.metric_name ?? "");
                            setEditMetricText(candidate.metric_text ?? "");
                            setEditMetricValue(candidate.metric_value?.toString() ?? "");
                            setEditMetricScale(candidate.metric_scale ?? "percent");
                            setEditMetricDirection(candidate.metric_direction ?? "success");
                            setEditMetricComparator(candidate.metric_comparator ?? "eq");
                          }}
                        >修改并接受</Button>
                        <Button
                          danger icon={<X size={16} />} loading={busy === candidate.id}
                          onClick={() => { setRejecting(candidate); setRejectionNotes(""); }}
                        >拒绝</Button>
                        <Button
                          disabled={candidate.validation_status !== "valid"}
                          icon={<Check size={16} />} loading={busy === candidate.id}
                          onClick={() => void review(candidate, "accepted")} type="primary"
                        >接受</Button>
                      </Flex>
                    ) : null}
                  </Space>
                </Card>
              </List.Item>
            )}
          />
          <Flex justify="flex-end">
            <Button
              disabled={publishDisabled} icon={<Send size={16} />} loading={busy === "publish"}
              onClick={() => void publish()} type="primary"
            >{run.status === "published" ? "已发布" : "发布已接受证据"}</Button>
          </Flex>
        </>
      ) : null}


      <Modal
        okButtonProps={{ disabled: !editQuestion.trim() || !editQuote.trim() }}
        okText="重新校验并接受"
        onCancel={() => setEditing(null)}
        onOk={() => editing ? void review(editing, "accepted", "Candidate corrected and source-revalidated.", {
          question_number: editQuestion,
          page_number: editPage,
          quote: editQuote,
          evidence_level: editing.evidence_level,
          metric_name: editing.evidence_level === "A" ? editMetricName : null,
          metric_text: editing.evidence_level === "A" ? editMetricText : null,
          metric_value: editing.evidence_level === "A" ? Number(editMetricValue) : null,
          metric_scale: editing.evidence_level === "A" ? editMetricScale : null,
          metric_direction: editing.evidence_level === "A" ? editMetricDirection : null,
          metric_comparator: editing.evidence_level === "A" ? editMetricComparator : null,
        }) : undefined}
        open={editing !== null}
        title="修改候选证据"
      >
        <Alert message="修改后会重新读取冻结源文件，校验页码、逐字引文和试卷题号。" showIcon type="warning" />
        <Space orientation="vertical" style={{ marginTop: 16, width: "100%" }}>
          <Input aria-label="修正题号" onChange={(event) => setEditQuestion(event.target.value)} value={editQuestion} />
          <Input aria-label="修正页码" min={1} onChange={(event) => setEditPage(Number(event.target.value))} type="number" value={editPage} />
          <Input.TextArea aria-label="修正逐字引文" onChange={(event) => setEditQuote(event.target.value)} rows={5} value={editQuote} />

          {editing?.evidence_level === "A" ? (
            <>
              <Input aria-label="修正指标名称" onChange={(event) => setEditMetricName(event.target.value)} placeholder="指标名称" value={editMetricName} />
              <Input.TextArea aria-label="修正指标原文" onChange={(event) => setEditMetricText(event.target.value)} placeholder="包含数值、限定词和方向语义的逐字原文" rows={2} value={editMetricText} />
              <Input aria-label="修正指标值" onChange={(event) => setEditMetricValue(event.target.value)} type="number" value={editMetricValue} />
              <Select aria-label="修正指标尺度" onChange={setEditMetricScale} options={[{ label: "百分比", value: "percent" }, { label: "比例", value: "proportion" }]} value={editMetricScale} />
              <Select aria-label="修正指标方向" onChange={setEditMetricDirection} options={[{ label: "成功率", value: "success" }, { label: "困难/错误率", value: "difficulty" }]} value={editMetricDirection} />
              <Select aria-label="修正指标限定词" onChange={setEditMetricComparator} options={[{ label: "精确等于", value: "eq" }, { label: "约等于", value: "approx" }, { label: "大于", value: "gt" }, { label: "大于等于", value: "gte" }, { label: "小于", value: "lt" }, { label: "小于等于", value: "lte" }]} value={editMetricComparator} />
            </>
          ) : null}
        </Space>
      </Modal>

      <Modal
        okButtonProps={{ danger: true, disabled: !rejectionNotes.trim() }}
        okText="确认拒绝" onCancel={() => setRejecting(null)}
        onOk={() => rejecting ? void review(rejecting, "rejected", rejectionNotes) : undefined}
        open={rejecting !== null} title="拒绝候选证据"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Text>拒绝原因会写入追加式审核记录，不能覆盖历史。</Text>
          <Input.TextArea
            aria-label="拒绝原因" onChange={(event) => setRejectionNotes(event.target.value)}
            placeholder="说明引文、题号或指标为何不可接受" rows={4} value={rejectionNotes}
          />
        </Space>
      </Modal>
    </Space>
  );
}
