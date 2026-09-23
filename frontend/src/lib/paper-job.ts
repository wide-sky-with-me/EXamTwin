import type { PaperJobQuestion, PaperJobResult } from "../types";

export const PAPER_JOB_STATUS_LABELS = {
  queued: "等待处理",
  parsing: "解析中",
  vision_review: "核对题面",
  splitting: "识别题目",
  answering: "作答中",
  completed: "处理完成",
  partial_failed: "部分题目失败",
  failed: "处理失败",
} satisfies Record<PaperJobResult["status"], string>;

export const PAPER_JOB_STAGE_LABELS = {
  queued: "等待处理",
  parsing: "解析试卷",
  vision_review: "核对题面",
  splitting: "识别题目",
  answering: "逐题作答",
  completed: "处理完成",
} satisfies Record<PaperJobResult["stage"], string>;

export function paperQuestionStatusLabel(question: PaperJobQuestion): string {
  if (question.skipped_by_strategy && !question.error) return "按策略留空";
  if (question.status === "pending") {
    return question.attempts > 0
      ? `等待重试 · 已尝试 ${question.attempts} 次`
      : "等待作答";
  }
  if (question.status === "answering") return "作答中";
  if (question.status === "failed" || question.error) {
    return question.attempts > 0
      ? `作答失败 · 已尝试 ${question.attempts} 次`
      : "作答失败";
  }
  return question.grounded ? "已作答" : "证据不足";
}

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
  if (question.skipped_by_strategy) return false;
  return question.status === "failed"
    || (question.status === "completed" && isRequiredArtifactMissing(question));
}
