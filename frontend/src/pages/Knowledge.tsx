import { Network } from "lucide-react";
import { useEffect, useState } from "react";

import { difficultyOf, relationLabels } from "../lib/evidence";
import { InlineMarkdown } from "../components/Markdown";
import type { KnowledgePoint, KnowledgeRelation } from "../types";

export function Knowledge({
  points,
  relations,
}: {
  points: KnowledgePoint[];
  relations: KnowledgeRelation[];
}) {
  const [unit, setUnit] = useState("ALL");
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [expandedTopics, setExpandedTopics] = useState<Set<string>>(() => new Set());
  const units = [
    "ALL",
    ...points
      .filter((point) => point.features.node_type === "unit")
      .map((point) => point.code),
  ];
  const visible = unit === "ALL" ? points : points.filter((point) => point.unit_code === unit);
  const topics = visible.filter((point) => point.features.node_type === "topic");
  const objectives = visible.filter(
    (point) => point.features.node_type === "learning_objective",
  );
  const selected =
    visible.find((point) => point.code === selectedCode) ??
    topics[0] ??
    objectives[0] ??
    null;
  const selectedRelations = selected
    ? relations.filter(
        (relation) =>
          relation.source_code === selected.code || relation.target_code === selected.code,
      )
    : [];
  const visibleCodes = new Set(visible.map((point) => point.code));
  const visiblePrerequisites = relations.filter(
    (relation) =>
      relation.relation_type === "prerequisite_of"
      && visibleCodes.has(relation.source_code)
      && visibleCodes.has(relation.target_code),
  );
  const selectedDifficulty = selected ? difficultyOf(selected) : null;
  const selectedTopicCode = selected
    ? selected.features.node_type === "topic"
      ? selected.code
      : topics.find((topic) => topic.id === selected.parent_id)?.code ?? null
    : null;

  useEffect(() => {
    if (!selectedTopicCode) return;
    setExpandedTopics((current) => {
      if (current.has(selectedTopicCode)) return current;
      return new Set([...current, selectedTopicCode]);
    });
  }, [selectedTopicCode]);

  return (
    <section>
      <div className="page-heading compact">
        <div>
          <h1>从 Unit 下钻到可考查目标</h1>
          <p>Unit → 章节 → syllabus 学习目标；同时展示先修、顺序、难度方法与证据等级。</p>
        </div>
      </div>
      <div className="unit-tabs">
        {units.map((item) => (
          <button
            className={unit === item ? "active" : ""}
            onClick={() => {
              setUnit(item);
              setSelectedCode(null);
              setExpandedTopics(new Set());
            }}
            key={item}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="knowledge-metrics">
        <span><b>{topics.length}</b> 章节</span>
        <span><b>{objectives.length}</b> 学习目标</span>
        <span><b>{visiblePrerequisites.length}</b> 先修关系</span>
      </div>
      <div className="knowledge-layout">
        <article className="panel knowledge-tree">
          {topics.map((topic) => {
            const children = objectives.filter((item) => item.parent_id === topic.id);
            return (
              <details
                className={selected?.code === topic.code ? "active" : ""}
                key={topic.id}
                onToggle={(event) => {
                  const open = event.currentTarget.open;
                  setExpandedTopics((current) => {
                    if (current.has(topic.code) === open) return current;
                    const next = new Set(current);
                    if (open) next.add(topic.code);
                    else next.delete(topic.code);
                    return next;
                  });
                }}
                open={expandedTopics.has(topic.code)}
              >
                <summary onClick={() => setSelectedCode(topic.code)}>
                  <span><code>{topic.code}</code><strong><InlineMarkdown>{topic.title}</InlineMarkdown></strong></span>
                  <em>{children.length} 项</em>
                </summary>
                <div>
                  {children.map((child) => (
                    <button
                      className={selected?.code === child.code ? "active" : ""}
                      key={child.id}
                      onClick={() => setSelectedCode(child.code)}
                    >
                      <code>{child.code}</code>
                      <span><InlineMarkdown>{child.title}</InlineMarkdown></span>
                      <b>{child.difficulty_score.toFixed(2)}</b>
                    </button>
                  ))}
                </div>
              </details>
            );
          })}
        </article>
        <article className="panel knowledge-detail">
          {!selected ? <div className="empty"><Network size={34} /><p>请选择知识节点</p></div> : (
            <>
              <div className="knowledge-detail-head">
                <div><code>{selected.code}</code><h2><InlineMarkdown>{selected.title}</InlineMarkdown></h2></div>
                <span className={`level level-${selected.evidence_level.toLowerCase()}`}>
                  {selected.evidence_level} 级证据
                </span>
              </div>
              {(selected.breadcrumb || selected.path?.length) && (
                <p className="knowledge-breadcrumb">
                  <InlineMarkdown>
                    {selected.breadcrumb ?? selected.path?.map((item) => item.title).join(" › ") ?? ""}
                  </InlineMarkdown>
                </p>
              )}
              {(selected.definition || selected.features.description) && (
                <p className="knowledge-definition">
                  <InlineMarkdown>
                    {String(selected.definition ?? selected.features.description ?? "")}
                  </InlineMarkdown>
                </p>
              )}
              <div className="difficulty-card">
                <div><span>正则化难度</span><strong>{selectedDifficulty?.score.toFixed(2)}</strong></div>
                <div className="difficulty"><span><i style={{ width: `${(selectedDifficulty?.score ?? 0) * 100}%` }} /></span></div>
                <small>
                  {selectedDifficulty?.label} · {selectedDifficulty?.evidence_level} 级证据 ·
                  置信度 {Math.round((selectedDifficulty?.confidence ?? 0) * 100)}%
                </small>
                <p>{selectedDifficulty?.rationale}</p>
              </div>
              <dl className="knowledge-meta">
                <div><dt>层级</dt><dd>{String(selected.features.node_type ?? "topic")}</dd></div>
                <div><dt>分支</dt><dd>{selected.strand}</dd></div>
                <div><dt>大纲页</dt><dd>{String(selected.features.syllabus_page ?? "—")}</dd></div>
                <div><dt>难度方法</dt><dd>{selectedDifficulty?.method}</dd></div>
              </dl>
              <h3>直接关系</h3>
              <div className="relation-list">
                {selectedRelations.length === 0 && <p>当前没有直接关系。</p>}
                {selectedRelations.map((relation) => {
                  const outgoing = relation.source_code === selected.code;
                  return (
                    <button
                      key={relation.id}
                      onClick={() => setSelectedCode(
                        outgoing ? relation.target_code : relation.source_code,
                      )}
                    >
                      <span>{relationLabels[relation.relation_type] ?? relation.relation_type}</span>
                      <b>{outgoing ? "→" : "←"}</b>
                      <strong>
                        <InlineMarkdown>
                          {outgoing ? relation.target_title : relation.source_title}
                        </InlineMarkdown>
                      </strong>
                      <small>{Math.round(relation.confidence * 100)}%</small>
                    </button>
                  );
                })}
              </div>
              <div className="source-ref">来源：{selected.source_ref}</div>
            </>
          )}
        </article>
      </div>
    </section>
  );
}
