import type { components } from "./generated/openapi";

type Schemas = components["schemas"];

// Public API models come from FastAPI's committed OpenAPI snapshot. Keep only
// UI-only compositions in this file so backend schema changes cannot silently drift.
export type Stats = Schemas["StatsResponse"];
export type Health = Schemas["HealthResponse"];
export type SubjectPack = Omit<Schemas["SubjectPackResponse"], "icon" | "color"> & {
  icon?: Schemas["SubjectPackResponse"]["icon"];
  color?: string;
};
export type SubjectStatus = Omit<Schemas["SubjectStatusResponse"], "icon" | "color"> & {
  icon?: Schemas["SubjectStatusResponse"]["icon"];
  color?: string;
};
export type PlatformStatus = Omit<Schemas["PlatformStatusResponse"], "subjects"> & {
  subjects: SubjectStatus[];
};
export type KnowledgePoint = Schemas["KnowledgePointResponse"];
export type KnowledgeRelation = Schemas["KnowledgeRelationResponse"];
export type Citation = Schemas["Citation"];
export type DiagramElement = Schemas["DiagramElement"];
export type DiagramLegendItem = Schemas["DiagramLegendItem"];
export type PaperDiagramSource = Schemas["PaperDiagramSource"];
export type AnswerDiagram = Schemas["AnswerDiagram"];
export type AnswerImage = Schemas["AnswerImage"];
export type AskResult = Schemas["AskResponse"];
export type PaperKnowledgeReference = Schemas["PaperKnowledgeReference"];
export type KnowledgePathNode = Schemas["KnowledgePathItem"];
export type KnowledgeRelationSummary = Schemas["KnowledgeRelationSummary"];
export type KnowledgeDifficulty = Schemas["KnowledgeDifficultySummary"];
export type PaperJobCreated = Schemas["PaperJobCreated"];
export type AgentStepSummary = Schemas["AgentStepSummary"];
export type AnswerRequirement = Schemas["SubpartRequirement"];
export type PaperJobQuestion = Schemas["PaperJobQuestion"];
export type SourceContextResult = Schemas["SourceContextResponse"];
export type PaperJobChunk = Schemas["PaperJobChunk"];
export type PaperJobResult = Omit<Schemas["PaperJobResponse"], "display_name"> & {
  display_name?: string | null;
};
export type PaperJobList = Omit<Schemas["PaperJobListResponse"], "items"> & {
  items: PaperJobSummary[];
};
export type PaperJobBulkDeleteResult = Schemas["PaperJobBulkDeleteResponse"];
export type PaperJobSummary = Omit<Schemas["PaperJobSummary"], "display_name"> & {
  display_name?: string | null;
};
export type PaperJobHistoryStatus = PaperJobSummary["status"] | "active";
export type RubricAward = Schemas["RubricAward"];
export type SymbolicCheck = Schemas["SymbolicCheck"];
export type GradeResult = Schemas["GradeResponse"];
export type ReviewItem = Schemas["ReviewQueueItem"];
export type InventoryResult = Schemas["InventoryResponse"];
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
export type AiRubricCriterionReview = Schemas["AiRubricCriterionReviewResponse"];
export type BatchRubricCriterionDecision = Schemas["BatchRubricCriterionDecision"];
export type BatchReviewRubricCriteriaRequest = Schemas["BatchReviewRubricCriteriaRequest"];
export type AiReviewRubricCriteriaRequest = Schemas["AiReviewRubricCriteriaRequest"];
export type GradingOverviewQuestion = Schemas["GradingOverviewQuestionResponse"];
export type GradingOverviewResponse = Schemas["GradingOverviewResponse"];
export type GraphVersion = Schemas["GraphVersionResponse"];
export type GraphVersionSummary = Schemas["GraphVersionSummary"];
export type GraphNode = Schemas["GraphNodeResponse"];
export type GraphEdge = Schemas["GraphEdgeResponse"];

export type PaperJobStatus = PaperJobResult["status"];
export type DiagramTone = NonNullable<DiagramElement["tone"]>;
export type EvidenceRole = NonNullable<Citation["evidence_role"]>;
