import type { components } from "./generated/openapi";

type Schemas = components["schemas"];

// Public API models come from FastAPI's committed OpenAPI snapshot. Keep only
// UI-only compositions in this file so backend schema changes cannot silently drift.
export type SubjectPack = Omit<
  Schemas["SubjectPackResponse"],
  "icon" | "color" | "source_booklet_required"
> & {
  icon?: Schemas["SubjectPackResponse"]["icon"];
  color?: string;
  source_booklet_required?: boolean;
};
export type SubjectStatus = Omit<
  Schemas["SubjectStatusResponse"],
  "icon" | "color" | "source_booklet_required"
> & {
  icon?: Schemas["SubjectStatusResponse"]["icon"];
  color?: string;
  source_booklet_required?: boolean;
};
export type PlatformStatus = Omit<Schemas["PlatformStatusResponse"], "subjects"> & {
  subjects: SubjectStatus[];
};
export type KnowledgePoint = Schemas["KnowledgePointResponse"];
export type Citation = Schemas["Citation"];
export type DiagramElement = Schemas["DiagramElement"];
export type AnswerDiagram = Schemas["AnswerDiagram"];
export type AnswerImage = Schemas["AnswerImage"];
export type PaperKnowledgeReference = Schemas["PaperKnowledgeReference"];
export type KnowledgeDifficulty = Schemas["KnowledgeDifficultySummary"];
export type PaperJobCreated = Schemas["PaperJobCreated"];
export type PaperJobQuestion = Schemas["PaperJobQuestion"];
export type SourceContextResult = Schemas["SourceContextResponse"];
export type PaperJobResult = Omit<
  Schemas["PaperJobResponse"],
  | "display_name"
  | "answer_mode"
  | "pair_key"
  | "source_booklet_document_id"
  | "source_booklet_checksum"
  | "source_booklet_filename"
> & {
  display_name?: string | null;
  answer_mode?: "generated" | "uploaded";
  pair_key?: string | null;
  source_booklet_document_id?: string | null;
  source_booklet_checksum?: string | null;
  source_booklet_filename?: string | null;
};
export type PaperJobList = Omit<Schemas["PaperJobListResponse"], "items"> & {
  items: PaperJobSummary[];
};
export type PaperJobBulkDeleteResult = Schemas["PaperJobBulkDeleteResponse"];
export type PaperJobSummary = Omit<
  Schemas["PaperJobSummary"],
  | "display_name"
  | "answer_mode"
  | "pair_key"
  | "source_booklet_document_id"
  | "source_booklet_checksum"
  | "source_booklet_filename"
> & {
  display_name?: string | null;
  answer_mode?: "generated" | "uploaded";
  pair_key?: string | null;
  source_booklet_document_id?: string | null;
  source_booklet_checksum?: string | null;
  source_booklet_filename?: string | null;
};
export type PaperJobHistoryStatus = PaperJobSummary["status"] | "active";
export type GradeResult = Schemas["GradeResponse"];
export type ReviewItem = Schemas["ReviewQueueItem"];
export type SourceDocument = Omit<Schemas["SourceDocumentResponse"], "display_name"> & {
  display_name?: string | null;
};
export type GradingPaper = Omit<Schemas["GradingPaperSummary"], "display_name"> & {
  display_name?: string | null;
};
export type RubricSetSummary = Schemas["RubricSetSummary"];
export type RubricSet = Schemas["RubricSetResponse"];
export type RubricCriterionPatch = Schemas["RubricCriterionPatch"];
export type PaperAssessment = Schemas["PaperAssessmentResponse"];
export type BatchRubricCriterionDecision = Schemas["BatchRubricCriterionDecision"];
export type BatchReviewRubricCriteriaRequest = Schemas["BatchReviewRubricCriteriaRequest"];
export type AiReviewRubricCriteriaRequest = Schemas["AiReviewRubricCriteriaRequest"];
export type GradingOverviewResponse = Schemas["GradingOverviewResponse"];
export type DiagramTone = NonNullable<DiagramElement["tone"]>;
