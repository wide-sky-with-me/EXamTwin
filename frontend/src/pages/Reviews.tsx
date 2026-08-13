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
import { CheckCircle2, Eye, LoaderCircle, PencilLine, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";

import { ErrorBanner } from "../components/Feedback";
import { useToast } from "../components/toast-context";
import { AppConfirmDialog } from "../components/ui/AppConfirmDialog";
import { reviewAssessment } from "../lib/api";
import type { ReviewItem } from "../types";

const REVIEWER_STORAGE_KEY = "examtwin.reviewerName";
const { Paragraph, Text, Title } = Typography;

type PendingReview = {
  decision: "confirm" | "override";
  item: ReviewItem;
  overrideMark: number | null;
  reviewer: string;
};

function confidenceTone(confidence: number): "success" | "normal" | "exception" {
  if (confidence >= 0.8) return "success";
  if (confidence >= 0.55) return "normal";
  return "exception";
}

function EvidenceDrawer({ item, onClose }: { item: ReviewItem | null; onClose: () => void }) {
  const result = item?.result;
  return (
    <Drawer
      destroyOnHidden
      size="large"
      onClose={onClose}
      open={item !== null}
      title={item ? `${item.question_ref ?? item.id.slice(0, 8)} · 评分证据` : "评分证据"}
    >
      {item && result && (
        <Space orientation="vertical" size="large" style={{ width: "100%" }}>
          <Row gutter={12}>
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
    <Space orientation="vertical" size="large" style={{ width: "100%" }}>
      <Flex align="flex-end" justify="space-between" wrap gap="middle">
        <div>
          <Title level={1} style={{ marginBottom: 4 }}>复核工作台</Title>
          <Paragraph type="secondary" style={{ margin: 0 }}>先核对评分原子、符号校验和引用证据，再确认或改分。</Paragraph>
        </div>
        {items.length > 0 && <Tag color="warning" icon={<ShieldAlert size={14} />}>{items.length} 项待处理 · {subjectCount} 个科目</Tag>}
      </Flex>

      {items.length > 0 && (
        <Card size="small">
          <Form layout="vertical">
            <Form.Item extra="复核人会写入审计记录；确认沿用建议分，改分需要填写最终分数。" label="复核人" required style={{ marginBottom: 0 }}>
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
        <Card><Empty description="当前没有待复核评分" image={<CheckCircle2 color="#237a5b" size={48} />} /></Card>
      ) : (
        <Row gutter={[16, 16]}>
          {items.map((item) => (
            <Col key={item.id} lg={12} xs={24}>
              <Card
                actions={[
                  <Button icon={<Eye size={16} />} key="evidence" onClick={() => setSelectedItem(item)} type="link">查看证据</Button>,
                  <Button disabled={busy === item.id} icon={busy === item.id ? <LoaderCircle className="spin" size={16} /> : <CheckCircle2 size={16} />} key="confirm" onClick={() => requestReview(item, "confirm")} type="link">确认评分</Button>,
                ]}
                title={<Space><Text code>{item.question_ref ?? item.id.slice(0, 8)}</Text><Tag>{item.subject_code}</Tag></Space>}
              >
                <Row align="middle" gutter={20}>
                  <Col span={7}><Statistic suffix={`/${item.total_available}`} title="模型建议" value={item.total_awarded} /></Col>
                  <Col span={9}>
                    <Text type="secondary">置信度</Text>
                    <Progress percent={Math.round(item.confidence * 100)} size="small" status={confidenceTone(item.confidence)} />
                  </Col>
                  <Col span={8}><Statistic title="评分原子" value={item.result.rubric_awards.length} /></Col>
                </Row>
                <Flex align="flex-end" gap="small" justify="space-between" style={{ marginTop: 20 }} wrap>
                  <Form.Item label="最终得分" style={{ margin: 0 }}>
                    <InputNumber
                      aria-label={`${item.question_ref ?? item.id} 最终得分`}
                      max={item.total_available}
                      min={0}
                      onChange={(value) => setOverrideMarks((current) => ({ ...current, [item.id]: value == null ? "" : String(value) }))}
                      placeholder={String(item.total_awarded)}
                      step={0.5}
                      value={overrideMarks[item.id] === "" || overrideMarks[item.id] === undefined ? null : Number(overrideMarks[item.id])}
                    />
                  </Form.Item>
                  <Button danger icon={<PencilLine size={16} />} onClick={() => requestReview(item, "override")}>改分并确认</Button>
                </Flex>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <EvidenceDrawer item={selectedItem} onClose={() => setSelectedItem(null)} />
      <AppConfirmDialog
        busy={pendingReview ? busy === pendingReview.item.id : false}
        confirmLabel={pendingReview?.decision === "override" ? "确认改分" : "确认评分"}
        danger={pendingReview?.decision === "override"}
        description={pendingReview
          ? pendingReview.decision === "override"
            ? `将 Q${pendingReview.item.question_ref?.replace(/^Q/i, "") ?? pendingReview.item.id.slice(0, 8)} 改为 ${pendingReview.overrideMark}/${pendingReview.item.total_available}，并写入最终评分。此操作不能在当前界面撤销。`
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
