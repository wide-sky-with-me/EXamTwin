import type { GradingPaper, SourceDocument } from "../types";

export function paperMaterialMeta(item: GradingPaper): string {
  const completion = `${item.completed_questions}/${item.total_questions} 题`;
  const status = item.status === "completed" ? "作答完整" : `${item.failed_questions} 题需处理`;
  return `${item.unit_code || "未限定单元"} · ${completion} · ${status}`;
}

export function schemeMaterialMeta(item: SourceDocument): string {
  const authority = item.authority_tier === "official"
    ? "官方标准"
    : item.authority_tier === "ai_generated"
      ? "AI 临时标准"
      : "导入标准";
  const readiness = ["converted", "indexed"].includes(item.status) ? "内容就绪" : item.status;
  return `${authority}${item.page_count ? ` · ${item.page_count} 页` : ""} · ${readiness}`;
}
