import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Flex,
  Form,
  Input,
  InputNumber,
  List,
  Progress,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { CheckCircle2, Eye, FileText, LoaderCircle, PencilLine, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";

import { ErrorBanner } from "../components/Feedback";
import { useToast } from "../components/toast-context";
import { AppConfirmDialog } from "../components/ui/AppConfirmDialog";
import { reviewAssessment } from "../lib/api";
import type { ReviewItem } from "../types";

const REVIEWER_STORAGE_KEY = "examtwin.reviewerName";
const { Text, Title } = Typography;

type PendingReview = {
  decision: "confirm" | "override";
  item: ReviewItem;
  overrideMark: number | null;
  reviewer: string;
};

type PendingReviewGroup = {
  key: string;
  kind: "paper" | "standalone";
  label: string;
  paperFilename: string | null;
  paperJobId: string | null;
  items: ReviewItem[];
};

const REVIEW_COLLATOR = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});

function reviewItemLabel(item: ReviewItem): string {
  if (item.question_ref?.trim()) return item.question_ref.trim();
  if (item.question_position !== null) return `Q${item.question_position + 1}`;
  return item.id.slice(0, 8);
}

function compareReviewItems(left: ReviewItem, right: ReviewItem): number {
  const leftPosition = left.question_position ?? Number.MAX_SAFE_INTEGER;
  const rightPosition = right.question_position ?? Number.MAX_SAFE_INTEGER;
  if (leftPosition !== rightPosition) return leftPosition - rightPosition;
  const question = REVIEW_COLLATOR.compare(reviewItemLabel(left), reviewItemLabel(right));
  if (question !== 0) return question;
  const created = REVIEW_COLLATOR.compare(left.created_at, right.created_at);
  return created !== 0 ? created : REVIEW_COLLATOR.compare(left.id, right.id);
}

function groupPendingReviews(items: ReviewItem[]): PendingReviewGroup[] {
  const linked = new Map<string, ReviewItem[]>();
  const standalone: ReviewItem[] = [];

  for (const item of items) {
    if (!item.paper_job_id) {
      standalone.push(item);
      continue;
    }
    const groupItems = linked.get(item.paper_job_id);
    if (groupItems) groupItems.push(item);
    else linked.set(item.paper_job_id, [item]);
  }

  const paperGroups = [...linked.entries()]
    .sort(([leftId], [rightId]) => REVIEW_COLLATOR.compare(leftId, rightId))
    .map<PendingReviewGroup>(([paperJobId, groupItems]) => {
      const orderedItems = [...groupItems].sort(compareReviewItems);
      const displayName = groupItems
        .map((item) => item.paper_display_name?.trim())
        .filter((value): value is string => Boolean(value))
        .sort(REVIEW_COLLATOR.compare)[0] ?? null;
      const filename = groupItems
        .map((item) => item.paper_filename?.trim())
        .filter((value): value is string => Boolean(value))
        .sort(REVIEW_COLLATOR.compare)[0] ?? null;
      return {
        key: `paper:${paperJobId}`,
        kind: "paper",
        label: displayName || filename || "未命名试卷",
        paperFilename: filename,
        paperJobId,
        items: orderedItems,
      };
    });

  const standaloneGroups = [...standalone]
    .sort(compareReviewItems)
    .map<PendingReviewGroup>((item) => ({
      key: `legacy:${item.id}`,
      kind: "standalone",
      label: `独立评估 · ${reviewItemLabel(item)}`,
      paperFilename: null,
      paperJobId: null,
      items: [item],
    }));

  return [...paperGroups, ...standaloneGroups];
}

function confidenceTone(confidence: number): "success" | "normal" | "exception" {
  if (confidence >= 0.8) return "success";
  if (confidence >= 0.55) return "normal";
  return "exception";
}

function ReviewQueueItem({
  busy,
  item,
  overrideValue,
  onOverrideValueChange,
  onRequestReview,
  onSelectEvidence,
}: {
  busy: boolean;
  item: ReviewItem;
  overrideValue: string | undefined;
  onOverrideValueChange: (value: string) => void;
  onRequestReview: (decision: "confirm" | "override") => void;
  onSelectEvidence: () => void;
}) {
  const label = reviewItemLabel(item);

  return (
    <article className="review-queue-item">
      <header className="review-queue-item-header">
        <Flex align="center" gap="small" wrap>
          <Text code>{label}</Text>
          <Tag>{item.subject_code}</Tag>
          <Tag color={item.answer_mode === "uploaded"
            ? "cyan"
            : item.answer_mode === "generated"
              ? "blue"
              : undefined}
          >
            {item.answer_mode === "uploaded"
              ? "外部答卷"
              : item.answer_mode === "generated"
                ? "AI 作答"
                : "来源未记录"}
          </Tag>
          {item.question_position !== null && (
            <Text type="secondary">题位 {item.question_position + 1}</Text>
          )}
        </Flex>
        <Text type="secondary">
          {new Date(item.created_at).toLocaleString("zh-CN")}
        </Text>
      </header>

      <div className="review-queue-item-metrics">
        <Statistic
          suffix={` / ${item.total_available}`}
          title="模型建议"
          value={item.total_awarded}
        />
        <div className="review-confidence">
          <Text type="secondary">置信度</Text>
          <Progress
            percent={Math.round(item.confidence * 100)}
            size="small"
            status={confidenceTone(item.confidence)}
          />
        </div>
        <Statistic title="评分原子" value={item.result.rubric_awards.length} />
      </div>

      <footer className="review-queue-item-actions">
        <Form.Item className="review-score-field" label="最终得分">
          <InputNumber
            aria-label={`${label} 最终得分`}
            max={item.total_available}
            min={0}
            onChange={(value) => onOverrideValueChange(value == null ? "" : String(value))}
            placeholder={String(item.total_awarded)}
            step={0.5}
            value={overrideValue === "" || overrideValue === undefined
              ? null
              : Number(overrideValue)}
          />
        </Form.Item>
        <div className="review-queue-actions">
          <Button icon={<Eye size={16} />} onClick={onSelectEvidence} type="link">
            查看证据
          </Button>
          <Button
            disabled={busy}
            icon={busy
              ? <LoaderCircle className="spin" size={16} />
              : <CheckCircle2 size={16} />}
            onClick={() => onRequestReview("confirm")}
            type="link"
          >
            确认评分
          </Button>
          <Button
            danger
            icon={<PencilLine size={16} />}
            onClick={() => onRequestReview("override")}
          >
            改分并确认
          </Button>
        </div>
      </footer>
    </article>
  );
}

function EvidenceDrawer({ item, onClose }: { item: ReviewItem | null; onClose: () => void }) {
  const result = item?.result;
  return (
    <Drawer
      destroyOnHidden
      rootClassName="review-evidence-drawer"
      size="large"
      onClose={onClose}
      open={item !== null}
      title={item ? `${reviewItemLabel(item)} · 评分证据` : "评分证据"}
    >
      {item && result && (
        <Space className="review-evidence-content" orientation="vertical" size="large">
          <Row className="review-evidence-stats" gutter={12}>
            <Col span={8}><Statistic suffix={` / ${item.total_available}`} title="模型建议分" value={item.total_awarded} /></Col>
            <Col span={8}><Statistic suffix="%" title="置信度" value={Math.round(item.confidence * 100)} /></Col>
            <Col span={8}><Statistic title="评分原子" value={result.rubric_awards.length} /></Col>
          </Row>
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="科目">{item.subject_code}</Descriptions.Item>
            <Descriptions.Item label="评估编号"><Text copyable code>{item.id}</Text></Descriptions.Item>
            <Descriptions.Item label="进入队列">{new Date(item.created_at).toLocaleString("zh-CN")}</Descriptions.Item>
          </Descriptions>

          <section>
            <Title level={4}>Rubric 判定</Title>
            {result.rubric_awards.length === 0 ? (
              <Empty description="没有可展示的 rubric 判定" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <List
                dataSource={result.rubric_awards}
                renderItem={(award) => (
                  <List.Item>
                    <List.Item.Meta
                      description={
                        <Space orientation="vertical" size={4}>
                          <Text>{award.rationale}</Text>
                          {award.student_evidence && <Text type="secondary">学生证据：{award.student_evidence}</Text>}
                          {award.improvement_suggestion && <Alert message={award.improvement_suggestion} showIcon type="info" />}
                        </Space>
                      }
                      title={
                        <Flex align="center" gap="small" wrap>
                          <Text strong>{award.description}</Text>
                          <Tag color={award.awarded === award.max_marks ? "success" : "warning"}>{award.awarded}/{award.max_marks}</Tag>
                          {award.mark_type && <Tag>{award.mark_type}</Tag>}
                        </Flex>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </section>

          {result.symbolic_checks.length > 0 && (
            <section>
              <Title level={4}>符号校验</Title>
              <List
                dataSource={result.symbolic_checks}
                renderItem={(check) => (
                  <List.Item>
                    <Space orientation="vertical" size={2}>
                      <Tag color={check.equivalent === true ? "success" : check.equivalent === false ? "error" : "default"}>
                        {check.equivalent === true ? "等价" : check.equivalent === false ? "不等价" : "未判定"}
                      </Tag>
                      <Text>{check.detail}</Text>
                      <Text type="secondary">学生：{check.student} · 期望：{check.expected}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            </section>
          )}

          {result.citations.length > 0 && (
            <section>
              <Title level={4}>引用证据</Title>
              <List
                dataSource={result.citations}
                renderItem={(citation) => (
                  <List.Item>
                    <List.Item.Meta
                      description={citation.excerpt}
                      title={`${citation.source}${citation.page ? ` · 第 ${citation.page} 页` : ""}`}
                    />
                  </List.Item>
                )}
              />
            </section>
          )}

          {(result.warnings.length > 0 || result.improvement_suggestions.length > 0) && (
            <Alert
              description={[...result.warnings, ...result.improvement_suggestions].join("；")}
              message="需要人工判断的信号"
              showIcon
              type="warning"
            />
          )}
        </Space>
      )}
    </Drawer>
  );
}

export function Reviews({ items, refresh }: { items: ReviewItem[]; refresh: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState(() => window.localStorage.getItem(REVIEWER_STORAGE_KEY) ?? "");
  const [overrideMarks, setOverrideMarks] = useState<Record<string, string>>({});
  const [pendingReview, setPendingReview] = useState<PendingReview | null>(null);
  const [selectedItem, setSelectedItem] = useState<ReviewItem | null>(items.length === 1 ? items[0] : null);
  const { notify } = useToast();

  const subjectCount = useMemo(() => new Set(items.map((item) => item.subject_id)).size, [items]);
  const reviewGroups = useMemo(() => groupPendingReviews(items), [items]);

  function requestReview(item: ReviewItem, decision: "confirm" | "override") {
    const reviewerName = reviewer.trim();
    if (!reviewerName) {
      setError("请填写复核人名称。");
      return;
    }
    const rawOverride = overrideMarks[item.id] ?? "";
    const overrideMark = Number(rawOverride);
    if (decision === "override" && (
      rawOverride.trim() === ""
      || !Number.isFinite(overrideMark)
      || overrideMark < 0
      || overrideMark > item.total_available
    )) {
      setError(`改分必须在 0–${item.total_available} 之间。`);
      return;
    }
    setError(null);
    setPendingReview({
      decision,
      item,
      overrideMark: decision === "override" ? overrideMark : null,
      reviewer: reviewerName,
    });
  }

  async function submitReview() {
    if (!pendingReview) return;
    const { decision, item, overrideMark, reviewer: reviewerName } = pendingReview;
    setBusy(item.id);
    setError(null);
    try {
      await reviewAssessment(item.subject_id, item.id, {
        reviewer: reviewerName,
        decision,
        override_mark: decision === "override" ? overrideMark : null,
      });
      window.localStorage.setItem(REVIEWER_STORAGE_KEY, reviewerName);
      notify(decision === "confirm" ? "评分已确认并写入审计记录。" : "改分已确认并写入审计记录。");
      setPendingReview(null);
      setSelectedItem(null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "复核失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Space className="reviews-page" orientation="vertical" size="large">
      <Flex align="flex-end" className="reviews-page-heading" justify="space-between" wrap gap="middle">
        <Title level={1}>复核</Title>
        {items.length > 0 && (
          <Tag color="warning" icon={<ShieldAlert size={14} />}>
            {items.length} 项待处理 · {subjectCount} 个科目
          </Tag>
        )}
      </Flex>

      {items.length > 0 && (
        <Card className="reviewer-card" size="small">
          <Form layout="vertical">
            <Form.Item
              className="reviewer-field"
              extra="复核人会写入审计记录；确认沿用建议分，改分需要填写最终分数。"
              label="复核人"
              required
            >
              <Input
                aria-label="复核人"
                onChange={(event) => {
                  const value = event.target.value;
                  setReviewer(value);
                  if (value.trim()) window.localStorage.setItem(REVIEWER_STORAGE_KEY, value);
                  else window.localStorage.removeItem(REVIEWER_STORAGE_KEY);
                }}
                placeholder="填写教师或复核人名称"
                value={reviewer}
              />
            </Form.Item>
          </Form>
        </Card>
      )}

      <ErrorBanner message={error} />

      {items.length === 0 ? (
        <Card className="reviews-empty">
          <Empty
            description="当前没有待复核评分"
            image={<CheckCircle2 className="reviews-empty-icon" size={48} />}
          />
        </Card>
      ) : (
        <div className="review-paper-groups">
          {reviewGroups.map((group, groupIndex) => {
            const pendingCount = group.items.length;
            const headingId = `review-group-${groupIndex}`;

            return (
              <section
                aria-labelledby={headingId}
                className={`review-paper-group ${group.kind}`}
                key={group.key}
              >
                <header className="review-paper-group-header">
                  <div className="review-paper-identity">
                    <span aria-hidden="true"><FileText size={20} /></span>
                    <div>
                      <Text type="secondary">
                        {group.kind === "paper" ? "关联试卷" : "独立复核项"}
                      </Text>
                      <Title id={headingId} level={2}>{group.label}</Title>
                      {group.kind === "paper" ? (
                        <Flex align="center" gap="small" wrap>
                          {group.paperFilename && group.paperFilename !== group.label && (
                            <Text type="secondary">{group.paperFilename}</Text>
                          )}
                          <Text code title={group.paperJobId ?? undefined}>
                            {group.paperJobId?.slice(0, 8)}
                          </Text>
                        </Flex>
                      ) : (
                        <Text type="secondary">未关联试卷 · 旧版或独立评估</Text>
                      )}
                    </div>
                  </div>
                  <div
                    aria-label={`本组待复核队列：${pendingCount} 项`}
                    className="review-paper-progress"
                  >
                    <Flex align="center" justify="space-between">
                      <Text strong>待复核队列</Text>
                      <Tag color="warning">{pendingCount} 项待复核</Tag>
                    </Flex>
                    <Text type="secondary">
                      已按题位顺序排列 · 提交后自动移出队列
                    </Text>
                  </div>
                </header>

                <div className="review-paper-items">
                  {group.items.map((item) => (
                    <ReviewQueueItem
                      busy={busy === item.id}
                      item={item}
                      key={item.id}
                      onOverrideValueChange={(value) => {
                        setOverrideMarks((current) => ({ ...current, [item.id]: value }));
                      }}
                      onRequestReview={(decision) => requestReview(item, decision)}
                      onSelectEvidence={() => setSelectedItem(item)}
                      overrideValue={overrideMarks[item.id]}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}

      <EvidenceDrawer item={selectedItem} onClose={() => setSelectedItem(null)} />
      <AppConfirmDialog
        busy={pendingReview ? busy === pendingReview.item.id : false}
        confirmLabel={pendingReview?.decision === "override" ? "确认改分" : "确认评分"}
        danger={pendingReview?.decision === "override"}
        description={pendingReview
          ? pendingReview.decision === "override"
            ? `将 ${reviewItemLabel(pendingReview.item)} 改为 ${pendingReview.overrideMark}/${pendingReview.item.total_available}，并写入最终评分。此操作不能在当前界面撤销。`
            : `将沿用建议分 ${pendingReview.item.total_awarded}/${pendingReview.item.total_available}，并写入最终评分。此操作不能在当前界面撤销。`
          : ""}
        onConfirm={submitReview}
        onOpenChange={(open) => { if (!open) setPendingReview(null); }}
        open={pendingReview !== null}
        title={pendingReview?.decision === "override" ? "确认改分？" : "确认评分？"}
      />
    </Space>
  );
}
