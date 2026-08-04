import {
  CircleGauge,
  Database,
  FileCheck2,
  LoaderCircle,
  Network,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";

import { apiClient, unwrapApi } from "../lib/api";
import { sourceLabels } from "../lib/evidence";
import type { Stats } from "../types";

export function Overview({
  stats,
  refresh,
  loading,
  postgresqlUp,
}: {
  stats: Stats | null;
  refresh: () => Promise<void>;
  loading: boolean;
  postgresqlUp: boolean | null;
}) {
  const [inventorying, setInventorying] = useState(false);
  const [notice, setNotice] = useState("");

  async function inventory() {
    setInventorying(true);
    setNotice("");
    try {
      const result = await unwrapApi(
        apiClient.POST("/api/v1/corpus/inventory", { body: { refresh: true } }),
      );
      const failureSummary = Object.entries(result.identity_failures)
        .map(([reason, count]) => `${reason} ${count} 份`)
        .join("；");
      setNotice(
        result.exam_identity_incomplete
          ? `已核验 ${result.scanned} 份资料；${result.exam_identity_incomplete} 份考试资料身份不完整，未进入严格配对${failureSummary ? `（${failureSummary}）` : ""}。`
          : `已核验 ${result.scanned} 份资料，全部考试资料身份均可判定。`,
      );
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "清点失败");
    } finally {
      setInventorying(false);
    }
  }

  const metrics = [
    ["资料总数", stats?.documents_total ?? "—", Database],
    ["严格 QP/MS 配对", stats?.strict_pairs ?? "—", FileCheck2],
    ["知识节点", stats?.knowledge_points ?? "—", Network],
    ["待人工复核", stats?.pending_reviews ?? "—", ShieldCheck],
  ] as const;

  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">9660 EVIDENCE FOUNDATION</p>
          <h1>让每一个答案，都能追溯到证据。</h1>
          <p>
            syllabus 定义知识边界，历年题建立考法，mark scheme 控制给分，
            examiner report 校准难度。
          </p>
        </div>
        <button className="secondary" onClick={inventory} disabled={inventorying}>
          {inventorying ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}
          重新清点资料
        </button>
      </div>

      {notice && <div className="notice">{notice}</div>}
      <div className="metric-grid">
        {metrics.map(([label, value, Icon]) => (
          <article className="metric-card" key={label}>
            <div className="metric-icon"><Icon size={19} /></div>
            <span>{label}</span>
            <strong>{loading ? "…" : value}</strong>
          </article>
        ))}
      </div>

      <div className="overview-grid">
        <article className="panel">
          <div className="panel-title">
            <div><span className="kicker">CORPUS</span><h2>资料构成</h2></div>
            <span className={`status ${postgresqlUp ? "" : "offline"}`}>
              <span /> {postgresqlUp ? "PostgreSQL live" : "PostgreSQL unavailable"}
            </span>
          </div>
          <div className="source-list">
            {Object.entries(stats?.documents_by_type ?? {})
              .sort((a, b) => b[1] - a[1])
              .map(([type, count]) => {
                const total = Math.max(stats?.documents_total ?? 1, 1);
                return (
                  <div className="source-row" key={type}>
                    <span>{sourceLabels[type] ?? type}</span>
                    <div className="bar"><i style={{ width: `${(count / total) * 100}%` }} /></div>
                    <b>{count}</b>
                  </div>
                );
              })}
          </div>
          {(stats?.exam_identity_incomplete ?? 0) > 0 && (
            <div className="notice warning">
              {stats?.exam_identity_incomplete} 份考试资料缺少年份、考季或 Unit，已从严格配对中排除。
            </div>
          )}
        </article>

        <article className="panel evidence-panel">
          <div className="panel-title">
            <div><span className="kicker">EVIDENCE POLICY</span><h2>证据等级</h2></div>
            <CircleGauge size={22} />
          </div>
          <div className="evidence-level"><b>A</b><div><strong>官方量化证据</strong><span>facility、mean mark、discrimination</span></div></div>
          <div className="evidence-level"><b>B</b><div><strong>官方定性证据</strong><span>考官报告中的常见错误与表现描述</span></div></div>
          <div className="evidence-level"><b>C</b><div><strong>历史估计</strong><span>经验证的题目表现代理量</span></div></div>
          <div className="evidence-level"><b>D</b><div><strong>冷启动推断</strong><span>知识深度、AO、解题步数；必须可被覆盖</span></div></div>
        </article>
      </div>

      <div className="guardrail">
        <ShieldCheck size={26} />
        <div>
          <strong>自动评分不直接发布</strong>
          <p>模型只提出 rubric 逐项证据与建议分；总分始终进入人工复核队列。</p>
        </div>
        <span>Human-in-the-loop</span>
      </div>
    </section>
  );
}
