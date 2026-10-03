import type { components } from "./generated/openapi";

type Schemas = components["schemas"];

// Public API models come from FastAPI's committed OpenAPI snapshot. Keep only
// UI-only compositions in this file so backend schema changes cannot silently drift.
export type SubjectPack = Schemas["SubjectPackResponse"];
export type SubjectStatus = Schemas["SubjectStatusResponse"];
export type PlatformStatus = Schemas["PlatformStatusResponse"];
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
export type PaperUnitDocument = Schemas["PaperUnitDocument"];
export type PaperUnitSummary = Schemas["PaperUnitSummary"];
export type PaperUnitList = Schemas["PaperUnitListResponse"];
export type PaperUnitAnswerCreated = Schemas["PaperUnitAnswerCreated"];
export type PaperJobResult = Schemas["PaperJobResponse"];
export type PaperJobList = Schemas["PaperJobListResponse"];
export type PaperJobBulkDeleteResult = Schemas["PaperJobBulkDeleteResponse"];
export type PaperJobSummary = Schemas["PaperJobSummary"];
export type PaperJobHistoryStatus = PaperJobSummary["status"] | "active";
export type GradeResult = Schemas["GradeResponse"];
export type ReviewItem = Schemas["ReviewQueueItem"];
export type SourceDocument = Schemas["SourceDocumentResponse"];
export type UploadedSourceDocument = Schemas["UploadedSourceDocumentResponse"];
export type GradingPaper = Schemas["GradingPaperSummary"];
export type RubricSetSummary = Schemas["RubricSetSummary"];
export type RubricSet = Schemas["RubricSetResponse"];
export type RubricCriterionPatch = Schemas["RubricCriterionPatch"];
export type PaperAssessment = Schemas["PaperAssessmentResponse"];
export type BatchRubricCriterionDecision = Schemas["BatchRubricCriterionDecision"];
export type BatchReviewRubricCriteriaRequest = Schemas["BatchReviewRubricCriteriaRequest"];
export type AiReviewRubricCriteriaRequest = Schemas["AiReviewRubricCriteriaRequest"];
export type GradingOverviewResponse = Schemas["GradingOverviewResponse"];
export type DiagramTone = NonNullable<DiagramElement["tone"]>;
