import type { components } from "../generated/openapi";
import "./target-score-strategy.css";

export type StrategyRequest = components["schemas"]["StrategyRequest"];
type StrategyPlan = components["schemas"]["StrategyPlan"];

export function TargetScoreFields({ value, onChange, economics = false }: {
  value: StrategyRequest | null;
  onChange: (value: StrategyRequest | null) => void;
  economics?: boolean;
}) {
  return <fieldset className="target-strategy-fields">
    <legend>目标分数模拟（可选）</legend>
    <label className="target-strategy-toggle"><input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked ? {
      target_score: 48, score_tolerance: 5, study_budget_minutes: 720,
      exam_budget_minutes: economics ? 105 : 90, reserve_minutes: 10,
      preparation: "基础概念已接触，但尚未系统练习本卷题型。",
    } : null)} />同时规划备考投入和考试时间</label>
    {value && <>
      <div className="target-strategy-grid">
        <label>目标分数<input type="number" required min={1} max={1000} step="0.5" value={value.target_score} onChange={(e) => onChange({ ...value, target_score: Number(e.target.value) })} /></label>
        <label>分数容差<input type="number" required min={0} max={50} value={value.score_tolerance} onChange={(e) => onChange({ ...value, score_tolerance: Number(e.target.value) })} /></label>
        <label>可备考时间（小时）<input type="number" required min={0.5} max={1600} step="0.5" value={value.study_budget_minutes / 60} onChange={(e) => onChange({ ...value, study_budget_minutes: Math.round(Number(e.target.value) * 60) })} /></label>
        <label>考试时长（分钟）<input type="number" required min={1} max={1440} value={value.exam_budget_minutes} onChange={(e) => onChange({ ...value, exam_budget_minutes: Number(e.target.value) })} /></label>
        <label>检查预留（分钟）<input type="number" required min={0} max={Math.min(120, value.exam_budget_minutes - 1)} value={value.reserve_minutes} onChange={(e) => onChange({ ...value, reserve_minutes: Number(e.target.value) })} /></label>
      </div>
      <label>当前基础与薄弱项<textarea maxLength={2000} rows={3} value={value.preparation} onChange={(e) => onChange({ ...value, preparation: e.target.value })} /></label>
      <p>请核对本卷考试时长。系统估计学习投入和学生作答时间，按推荐路径答题并留空其余部分；实际得分需另行评分。</p>
    </>}
  </fieldset>;
}

export function TargetScoreReport({ plan }: { plan: StrategyPlan }) {
  const route = plan.selected;
  const options = new Map(plan.analysis.options.map((option) => [option.id, option]));
  const names = { balanced: "均衡推荐（本次执行）", less_study: "较少备考投入", faster_exam: "较短考场用时" };
  const jsonUrl = `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(plan, null, 2))}`;
  return <section className="target-strategy-report" aria-label="目标分数策略">
    <h2>目标 {plan.request.target_score} / {plan.total_marks} 分 · {plan.status === "feasible_estimate" ? "已生成推荐路径" : "当前预算内未找到达标路径"}</h2>
    <p>规划 {route.expected_marks} 分 · 范围 {route.lower_marks}–{route.upper_marks} 分（假设按方案正确完成，非学生得分预测）。实际得分请使用独立评分；策略预估不能作为评分结果。</p>
    <p>预计备考 {(route.study_minutes / 60).toFixed(1)} / {(plan.request.study_budget_minutes / 60).toFixed(1)} 小时；作答 {route.exam_minutes} 分钟 + 检查 {plan.request.reserve_minutes} 分钟 / 考试 {plan.request.exam_budget_minutes} 分钟。</p>
    <details><summary>查看备考清单、答题顺序和方案比较</summary>
      <p>能力假设：{plan.request.preparation}</p>
      <ul>{plan.analysis.assumptions.map((text, index) => <li key={index}>{text}</li>)}</ul>
      <h3>本方案需要准备</h3>
      <ul>{plan.analysis.skills.filter((skill) => route.skill_codes.includes(skill.code)).map((skill) => <li key={skill.code}><strong>{skill.title}</strong> · 新增学习约 {skill.study_minutes} 分钟。{skill.learning_goal}</li>)}</ul>
      <h3>按此顺序作答</h3>
      <ol>{route.option_ids.map((id) => {
        const option = options.get(id)!;
        return <li key={id}><strong>第 {option.question_number} 题 {option.subpart === "whole" ? "" : option.subpart} · {option.mode === "full" ? "完整作答" : "部分作答"}</strong> · 预计 {option.expected_marks} 分，限时 {option.exam_minutes} 分钟，额外练习 {option.practice_minutes} 分钟。<p>{option.approach}</p>{option.stop_before && <p>停止边界：{option.stop_before}</p>}<p>{option.rationale}</p></li>;
      })}</ol>
      <p>达到各题时间预算时先跳过卡住的步骤，使用预留时间检查已完成答案。</p>
      <p>本次留空：{plan.skipped_subparts.join("、") || "无"}。这不表示相关知识长期无需学习。</p>
      <h3>相同目标下的时间取舍</h3>
      <ul>{[route, ...plan.alternatives].map((item) => <li key={item.name}>{names[item.name]}：备考 {(item.study_minutes / 60).toFixed(1)} 小时，作答 {item.exam_minutes} 分钟，预期 {item.expected_marks} 分。</li>)}</ul>
      <p>若各方案相同，表示本次搜索没有找到不同的时间取舍。比较方案仅供参考，本次答卷执行均衡推荐。</p>
      <a href={jsonUrl} download="target-score-strategy.json">下载完整策略</a>
    </details>
    <ul className="target-strategy-warnings">{plan.warnings.map((text, index) => <li key={index}>{text}</li>)}</ul>
  </section>;
}
