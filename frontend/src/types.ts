export type Stats = {
  documents_total: number;
  documents_by_type: Record<string, number>;
  documents_by_status: Record<string, number>;
  strict_pairs: number;
  orphan_question_papers: number;
  orphan_mark_schemes: number;
  knowledge_points: number;
  relations: number;
  question_difficulty_rows: number;
  pending_reviews: number;
  exam_identity_incomplete: number;
};

export type Health = {
  status: string;
  subject_code: string;
  api_contract_version?: string;
  capabilities?: string[];
};

export type SubjectPack = {
  id: string;
  subject_code: string;
  title: string;
  board_name: string;
  units: Array<{
    code: string;
    title: string;
    strand: string;
  }>;
};

export type KnowledgePoint = {
  id: string;
  code: string;
  title: string;
  unit_code: string;
  strand: string;
  parent_id: string | null;
  difficulty_score: number;
  difficulty_label: string;
  difficulty_confidence: number;
  evidence_level: string;
  source_ref: string;
  definition?: string;
  breadcrumb?: string;
  path?: KnowledgePathNode[];
  relations?: KnowledgeRelationSummary[];
  difficulty?: KnowledgeDifficulty;
  features: {
    node_type?: "unit" | "topic" | "learning_objective";
    description?: string;
    syllabus_page?: number;
    difficulty_method?: string;
    [key: string]: unknown;
  };
};

export type KnowledgeRelation = {
  id: number;
  source_code: string;
  source_title: string;
  target_code: string;
  target_title: string;
  relation_type: "contains" | "prerequisite_of" | "syllabus_sequence" | string;
  confidence: number;
  source_ref: string;
};

export type Citation = {
  source: string;
  document_id?: string;
  page?: number;
  section?: string;
  section_path?: string[];
  knowledge_code?: string;
  evidence_role?: EvidenceRole;
  content_url?: string;
  source_type?: string;
  authority_tier?: string;
  pair_key?: string;
  score?: number;
  excerpt: string;
};

export type DiagramTone =
  | "default"
  | "primary"
  | "secondary"
  | "tertiary"
  | "muted";

export type DiagramElement = {
  kind: "line" | "polyline" | "polygon" | "circle" | "ellipse" | "path" | "point" | "text";
  x1?: number;
  y1?: number;
  x2?: number;
  y2?: number;
  x?: number;
  y?: number;
  cx?: number;
  cy?: number;
  r?: number;
  rx?: number;
  ry?: number;
  points: [number, number][];
  d?: string;
  text?: string;
  dashed: boolean;
  emphasis: boolean;
  arrow_start: boolean;
  arrow_end: boolean;
  fill: "none" | "light" | "accent";
  tone?: DiagramTone;
};

export type DiagramLegendItem = {
  label: string;
  tone: DiagramTone;
};

export type AnswerDiagram = {
  title: string;
  caption: string;
  tool_name?: "math_plot" | "math_diagram";
  view_box: [number, number, number, number];
  elements: DiagramElement[];
  legend?: DiagramLegendItem[];
};

export type AnswerImage = {
  title: string;
  caption: string;
  tool_name: "image_generate";
  content_url: string;
  media_type: "image/png";
  width: number;
  height: number;
  generated: true;
};

export type AskResult = {
  answer_markdown: string;
  diagrams: AnswerDiagram[];
  images: AnswerImage[];
  citations: Citation[];
  confidence: number;
  grounded: boolean;
  warnings: string[];
};

export type PaperKnowledgeReference = {
  code: string;
  title: string;
  node_type: string;
  difficulty_score: number;
  difficulty_label: string;
  difficulty_confidence: number;
  evidence_level: string;
  source_ref: string;
  definition?: string;
  breadcrumb?: string;
  path?: KnowledgePathNode[];
  relations?: KnowledgeRelationSummary[];
  difficulty?: KnowledgeDifficulty;
  references: Citation[];
};

export type KnowledgePathNode = {
  code: string;
  title: string;
  node_type: string;
};

export type KnowledgeRelationSummary = {
  relation_type: string;
  direction: "outgoing" | "incoming";
  code: string;
  title: string;
  node_type: string;
  confidence: number;
  source_ref: string;
};

export type KnowledgeDifficulty = {
  score: number;
  label: string;
  confidence: number;
  evidence_level: string;
  method: string;
  rationale: string;
  features?: Record<string, number | string | boolean | null>;
};

export type EvidenceRole =
  | "definition"
  | "explanation"
  | "worked_example"
  | "assessment"
  | "marking"
  | string;

export type PaperQuestionAnswer = {
  number: string;
  question_markdown: string;
  diagrams: AnswerDiagram[];
  images: AnswerImage[];
  answer_markdown: string;
  citations: Citation[];
  knowledge_points: PaperKnowledgeReference[];
  confidence: number;
  grounded: boolean;
  warnings: string[];
  error?: string;
};

export type PaperJobCreated = {
  job_id: string;
  status: "queued";
  stage: "queued";
};

export type PaperJobStatus =
  | "queued"
  | "parsing"
  | "splitting"
  | "answering"
  | "completed"
  | "partial_failed"
  | "failed";

export type AgentStepSummary = {
  run_attempt: number;
  sequence: number;
  phase: "preparing" | "deciding" | "tool" | "verifying" | "finalizing";
  status: "running" | "completed" | "failed";
  tool_name?: string;
  message: string;
  created_at: string;
};

export type AnswerRequirement = {
  label: string;
  marks?: number;
  answer_kind: "text" | "numeric" | "expression" | "proof" | "table" | "math_plot" | "math_diagram" | "image";
  accuracy?: string;
  units?: string[];
  required_tool?: "math_plot" | "math_diagram" | "image_generate";
};

export type PaperJobQuestion = PaperQuestionAnswer & {
  position: number;
  attempts: number;
  source_pages: number[];
  source_warnings: string[];
  answer_requirements: AnswerRequirement[];
  total_marks?: number;
  agent_steps: AgentStepSummary[];
  status: "pending" | "answering" | "completed" | "failed";
};

export type SourceContextResult = {
  document_id: string;
  source: string;
  page?: number;
  content_markdown: string;
  truncated: boolean;
};

export type PaperJobChunk = {
  chunk_index: number;
  page_start: number;
  page_end: number;
  status: "pending" | "parsing" | "completed" | "failed";
  attempts: number;
  error?: string;
};

export type PaperJobResult = {
  job_id: string;
  filename: string;
  unit_code?: string;
  status: PaperJobStatus;
  stage: "queued" | "parsing" | "splitting" | "answering" | "completed";
  total_pages: number;
  parsed_pages: number;
  total_questions: number;
  completed_questions: number;
  failed_questions: number;
  error?: string;
  created_at: string;
  updated_at: string;
  chunks: PaperJobChunk[];
  questions: PaperJobQuestion[];
};

export type RubricAward = {
  criterion_id: string;
  description: string;
  mark_type?: string;
  max_marks: number;
  awarded: number;
  student_evidence?: string;
  rationale: string;
  confidence: number;
  source_ref?: string;
};

export type GradeResult = {
  assessment_id: string;
  question_ref?: string;
  total_awarded: number;
  total_available: number;
  confidence: number;
  status: string;
  rubric_awards: RubricAward[];
  citations: Citation[];
  warnings: string[];
  manual_review_required: boolean;
};

export type ReviewItem = {
  id: string;
  question_ref?: string;
  total_awarded: number;
  total_available: number;
  confidence: number;
  status: string;
  created_at: string;
  result: GradeResult;
};
