import type { PaperJobQuestion, PaperJobResult } from "../types";

export function paperProgress(job: PaperJobResult): number {
  const pageProgress = job.total_pages
    ? Math.round((job.parsed_pages / job.total_pages) * 100)
    : 0;
  const answeredProgress = job.total_questions
    ? Math.round(
        ((job.completed_questions + job.failed_questions) / job.total_questions) * 100,
      )
    : 0;

  if (job.status === "completed") return 100;
  if (job.status === "partial_failed") {
    const successfulProgress = job.total_questions
      ? Math.round((job.completed_questions / job.total_questions) * 40)
      : 0;
    return 60 + successfulProgress;
  }
  if (job.stage === "parsing") return Math.max(4, Math.round(pageProgress * 0.5));
  if (job.stage === "vision_review") return 52;
  if (job.stage === "splitting") return 55;
  if (job.stage === "answering") return 60 + Math.round(answeredProgress * 0.4);
  return 4;
}

function isRequiredArtifactMissing(question: PaperJobQuestion): boolean {
  return question.answer_requirements.some((requirement) => {
    if (requirement.required_tool === "image_generate") {
      return question.images.length === 0;
    }
    if (
      requirement.required_tool === "math_plot"
      || requirement.required_tool === "math_diagram"
    ) {
      return !question.diagrams.some(
        (diagram) => (diagram.tool_name ?? "math_diagram") === requirement.required_tool,
      );
    }
    return false;
  });
}

export function canRetryQuestion(question: PaperJobQuestion): boolean {
  return question.status === "failed"
    || (question.status === "completed" && isRequiredArtifactMissing(question));
}
