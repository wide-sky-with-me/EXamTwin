import type {
  KnowledgeDifficulty,
  KnowledgePoint,
  PaperKnowledgeReference,
} from "../types";

export const sourceLabels: Record<string, string> = {
  syllabus: "官方考纲",
  textbook: "教材",
  question_paper: "历年试卷",
  mark_scheme: "Mark scheme",
  examiner_report: "考官报告",
  insert: "Insert",
  revision_note: "复习笔记",
  topic_practice: "专题练习",
  slide: "课件",
  other: "其他",
};

export const relationLabels: Record<string, string> = {
  contains: "从属",
  prerequisite_of: "先修",
  syllabus_sequence: "大纲顺序",
};

export function difficultyOf(
  point: PaperKnowledgeReference | KnowledgePoint,
): KnowledgeDifficulty {
  const legacyMethod =
    "features" in point
      ? String(point.features?.difficulty_method ?? "cold-start")
      : "cold-start";
  const difficultyLabel = ["easy", "medium", "hard"].includes(point.difficulty_label)
    ? point.difficulty_label as KnowledgeDifficulty["label"]
    : "medium";
  return point.difficulty ?? {
    score: point.difficulty_score,
    label: difficultyLabel,
    confidence: point.difficulty_confidence,
    evidence_level: point.evidence_level,
    method: legacyMethod,
    rationale: "当前为课程结构冷启动估计，尚无官方量化或真实学生表现校准。",
    features: {},
  };
}
