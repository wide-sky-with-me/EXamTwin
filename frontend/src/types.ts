import type { components } from "./generated/openapi";

type Schemas = components["schemas"];

// Public API models come from FastAPI's committed OpenAPI snapshot. Keep only
// UI-only compositions in this file so backend schema changes cannot silently drift.
export type Stats = Schemas["StatsResponse"];
export type Health = Schemas["HealthResponse"];
export type SubjectPack = Schemas["SubjectPackResponse"];
export type SubjectStatus = Schemas["SubjectStatusResponse"];
export type PlatformStatus = Schemas["PlatformStatusResponse"];
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
export type PaperJobResult = Schemas["PaperJobResponse"];
export type RubricAward = Schemas["RubricAward"];
export type SymbolicCheck = Schemas["SymbolicCheck"];
export type GradeResult = Schemas["GradeResponse"];
export type ReviewItem = Schemas["ReviewQueueItem"];
export type InventoryResult = Schemas["InventoryResponse"];
export type SourceDocument = Schemas["SourceDocumentResponse"];
export type GradingPaper = Schemas["GradingPaperSummary"];
export type RubricSetSummary = Schemas["RubricSetSummary"];
export type RubricSet = Schemas["RubricSetResponse"];
export type PaperAssessment = Schemas["PaperAssessmentResponse"];
export type GraphVersion = Schemas["GraphVersionResponse"];
export type GraphVersionSummary = Schemas["GraphVersionSummary"];
export type GraphNode = Schemas["GraphNodeResponse"];
export type GraphEdge = Schemas["GraphEdgeResponse"];

export type PaperJobStatus = PaperJobResult["status"];
export type DiagramTone = NonNullable<DiagramElement["tone"]>;
export type EvidenceRole = NonNullable<Citation["evidence_role"]>;
