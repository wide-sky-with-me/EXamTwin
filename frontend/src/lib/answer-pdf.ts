import { degrees, PDFDocument, rgb, type PDFPage } from "pdf-lib";
import { getFontEmbedCSS, toCanvas } from "html-to-image";
import type { components } from "../generated/openapi";
import type { AnswerDiagram, AnswerImage, PaperJobResult } from "../types";

export type AnswerPdfLayout = components["schemas"]["PaperExportLayout"];
export type AnswerRegion = components["schemas"]["PaperAnswerRegion"];
export type AnswerSection = {
  id: string;
  position: number;
  number: string;
  anchor: string;
  markdown: string;
  diagrams: AnswerDiagram[];
  images: AnswerImage[];
  sourcePages: number[];
};
export type PdfPlacement = { page: number; x: number; y: number; width: number; height: number };

const normalize = (label: string) => label.replace(/\s/g, "").toLowerCase();

/** Split only at exact subpart headings, preserving every character and artifact. */
export function answerSections(job: PaperJobResult): AnswerSection[] {
  return job.questions.filter((q) => q.status === "completed" && q.answer_markdown && !q.error)
    .flatMap((q) => {
      const labels = q.answer_requirements.map((r) => normalize(r.label));
      const matches = [...q.answer_markdown.matchAll(/^###\s+([^\n]+)\n/gm)]
        .filter((m) => labels.includes(normalize(m[1])));
      const split = matches.length > 0 && new Set(matches.map((m) => normalize(m[1]))).size === matches.length;
      const parts = split ? matches.map((match, index) => ({
        anchor: match[1].trim(),
        markdown: q.answer_markdown.slice(index === 0 ? 0 : match.index, matches[index + 1]?.index),
      })) : [{ anchor: "whole", markdown: q.answer_markdown }];
      return parts.map((part, index) => {
        const belongs = (anchor: string | null) => {
          const known = parts.some((p) => normalize(p.anchor) === normalize(anchor ?? "whole"));
          return known ? normalize(anchor ?? "whole") === normalize(part.anchor) : index === parts.length - 1;
        };
        return {
          id: `${q.position}:${index}`, position: q.position, number: q.number,
          anchor: part.anchor, markdown: part.markdown, sourcePages: q.source_pages,
          diagrams: q.diagrams.filter((d) => belongs(d.answer_anchor)),
          images: q.images.filter((im) => belongs(im.answer_anchor)),
        };
      });
    });
}

export function suggestedRegion(section: AnswerSection, layout: AnswerPdfLayout): AnswerRegion | undefined {
  return layout.regions.find((r) => r.question_position === section.position
    && normalize(r.answer_anchor) === normalize(section.anchor));
}

export function validateRegions(sections: AnswerSection[], regions: Record<string, AnswerRegion>, layout: AnswerPdfLayout) {
  const used: AnswerRegion[] = [];
  for (const section of sections) {
    const r = regions[section.id];
    if (!r) throw new Error(`请为 Q${section.number} ${section.anchor === "whole" ? "" : section.anchor} 框选答题区。`);
    const page = layout.pages[r.page_number - 1];
    if (!page || !section.sourcePages.includes(r.page_number)
      || ![r.x, r.y, r.width, r.height].every(Number.isFinite)
      || r.x < 0 || r.y < 0 || r.width < 120 || r.height < 24
      || r.x + r.width > page.width + 0.1 || r.y + r.height > page.height + 0.1) {
      throw new Error(`Q${section.number} 答题区必须在对应原卷页内，且至少宽 120、高 24。`);
    }
    if (used.some((other) => other.page_number === r.page_number
      && r.x < other.x + other.width && r.x + r.width > other.x
      && r.y < other.y + other.height && r.y + r.height > other.y)) {
      throw new Error("答题区域相互重叠，请调整后再导出。");
    }
    used.push(r);
  }
  for (const section of sections) {
    for (const diagram of section.diagrams) {
      if (!diagram.source) continue;
      const source = diagram.source;
      const page = layout.pages[source.page_number - 1];
      if (!page || !section.sourcePages.includes(source.page_number)) throw new Error("原图叠绘的来源页不一致。");
      const [x, y, w, h] = diagram.view_box;
      const box = { x: x * page.width / source.width, y: y * page.height / source.height,
        width: w * page.width / source.width, height: h * page.height / source.height };
      if (used.some((r) => r.page_number === source.page_number
        && r.x < box.x + box.width && r.x + r.width > box.x
        && r.y < box.y + box.height && r.y + r.height > box.y)) {
        throw new Error("文字答题区与原图叠绘区域重叠，请重新框选文字区域。");
      }
    }
  }
}

/** Convert displayed top-left coordinates to PDF user space, including CropBox/Rotate. */
export function pdfImagePosition(page: PDFPage, p: PdfPlacement) {
  const crop = page.getCropBox();
  const rotation = ((page.getRotation().angle % 360) + 360) % 360;
  const common = { width: p.width, height: p.height, rotate: degrees(rotation) };
  switch (rotation) {
    case 0: return { ...common, x: crop.x + p.x, y: crop.y + crop.height - p.y - p.height };
    case 90: return { ...common, x: crop.x + p.y + p.height, y: crop.y + p.x };
    case 180: return { ...common, x: crop.x + crop.width - p.x, y: crop.y + p.y + p.height };
    case 270: return { ...common, x: crop.x + crop.width - p.y - p.height, y: crop.y + crop.height - p.x };
    default: throw new Error("试卷页面旋转角度不受支持。");
  }
}

function blankRow(pixels: Uint8ClampedArray, width: number, row: number) {
  for (let x = 0; x < width; x++) {
    const i = (row * width + x) * 4;
    if (pixels[i + 3] > 20 && Math.min(pixels[i], pixels[i + 1], pixels[i + 2]) < 240) return false;
  }
  return true;
}

function requireVisibleInk(canvas: HTMLCanvasElement) {
  const context = canvas.getContext("2d");
  if (!context) throw new Error("浏览器无法渲染答案。");
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  for (let i = 0; i < pixels.length; i += 4) {
    if (pixels[i + 3] > 20 && Math.min(pixels[i], pixels[i + 1], pixels[i + 2]) < 240) return;
  }
  throw new Error("答案或图形渲染为空，已停止导出以避免遗漏内容。");
}

/** Break in whitespace only. A formula or figure that cannot fit is never clipped. */
export function findRasterBreak(canvas: HTMLCanvasElement, start: number, available: number): number {
  const end = Math.min(canvas.height, start + Math.floor(available));
  if (end === canvas.height) return end;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("浏览器无法渲染答案。");
  const pixels = context.getImageData(0, start, canvas.width, end - start).data;
  for (let row = end - start - 2; row >= 12; row--) {
    if (blankRow(pixels, canvas.width, row) && blankRow(pixels, canvas.width, row - 1)) return start + row;
  }
  return start;
}

async function pngSlice(canvas: HTMLCanvasElement, from: number, to: number): Promise<string> {
  const slice = document.createElement("canvas");
  slice.width = canvas.width;
  slice.height = to - from;
  const context = slice.getContext("2d");
  if (!context) throw new Error("浏览器无法渲染答案。");
  context.drawImage(canvas, 0, from, canvas.width, to - from, 0, 0, slice.width, slice.height);
  return slice.toDataURL("image/png");
}

async function readyForCapture(element: HTMLElement) {
  await document.fonts.ready;
  await Promise.all([...element.querySelectorAll("img")].map(async (image) => {
    image.loading = "eager";
    await image.decode();
    if (!image.naturalWidth) throw new Error("答案图片未能加载，无法导出完整答案。");
  }));
  if (element.querySelector(".katex-error")) throw new Error("答案含无法排版的公式，请先修正答案。");
  if (element.querySelector("[data-pdf-missing-image]")) throw new Error("答案中有无法读取的图片，不能导出不完整的 PDF。");
  if (element.scrollWidth > element.clientWidth + 2) throw new Error("公式或表格超出答题区宽度，请加宽答题区。");
  if ([...element.querySelectorAll<HTMLElement>(".katex-display, table, pre")]
    .some((node) => node.scrollWidth > node.clientWidth + 2)) {
    throw new Error("公式或表格存在横向溢出，请加宽答题区。");
  }
}

async function captureAnswer(element: HTMLElement, fontEmbedCSS: string) {
  // html-to-image deep-clones SVG as a unit, bypassing style inlining of its
  // descendants. Freeze their computed styles, including foreignObject math,
  // so strokes/labels survive outside the application's stylesheet.
  const restored: { node: HTMLElement | SVGElement; style: string | null }[] = [];
  for (const node of element.querySelectorAll<HTMLElement | SVGElement>("svg *")) {
    restored.push({ node, style: node.getAttribute("style") });
    const computed = getComputedStyle(node);
    const values = Array.from(computed).map((key) => [key, computed.getPropertyValue(key)]);
    for (const [key, value] of values) node.style.setProperty(key, value);
  }
  try {
    const canvas = await toCanvas(element, { pixelRatio: 3, fontEmbedCSS, includeQueryParams: true });
    requireVisibleInk(canvas);
    return canvas;
  } finally {
    for (const { node, style } of restored) {
      if (style === null) node.removeAttribute("style"); else node.setAttribute("style", style);
    }
  }
}

export async function createAnswerPdf({ source, layout, job, sections, regions, elements, onProgress }: {
  source: ArrayBuffer;
  layout: AnswerPdfLayout;
  job: PaperJobResult;
  sections: AnswerSection[];
  regions: Record<string, AnswerRegion>;
  elements: Map<string, HTMLElement>;
  onProgress: (message: string) => void;
}): Promise<Uint8Array<ArrayBuffer>> {
  validateRegions(sections, regions, layout);
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", source))]
    .map((b) => b.toString(16).padStart(2, "0")).join("");
  if (digest !== layout.source_sha256) throw new Error("原试卷已变化，请重新打开导出窗口。");
  const pdf = await PDFDocument.load(source);
  if (pdf.getPageCount() !== layout.pages.length) throw new Error("原试卷页数不一致。");
  pdf.setTitle(`${job.display_name || job.filename} — AI answer draft`);
  pdf.setSubject(`ExamTwin AI answer draft; job ${job.job_id}; ${job.completed_questions}/${job.total_questions} questions completed`);
  if (job.strategy_plan) {
    const plan = job.strategy_plan;
    pdf.setSubject(`ExamTwin target-score simulation; target ${plan.request.target_score}/${plan.total_marks}; estimated ${plan.selected.expected_marks}, not graded; study ${plan.selected.study_minutes} min; exam ${plan.selected.exam_minutes} + reserve ${plan.request.reserve_minutes} min; ${plan.skipped_subparts.length} subparts intentionally blank`);
  }
  const firstElement = elements.values().next().value;
  if (!firstElement) throw new Error("没有可导出的答案。");
  await readyForCapture(firstElement);
  const fontEmbedCSS = await getFontEmbedCSS(firstElement, { preferredFontFormat: "woff2" });
  let extraPages = 0;
  const addPage = (title: string, width: number) => {
    if (++extraPages > 200) throw new Error("续答页超过 200 页，请检查答案长度。");
    const page = pdf.addPage([Math.max(595.28, width + 96), 841.89]);
    page.drawText(title, { x: 48, y: 805, size: 10, color: rgb(0.1, 0.2, 0.4) });
    page.drawText(`ExamTwin AI draft | PDF page ${pdf.getPageCount()} | ${job.completed_questions}/${job.total_questions} completed`,
      { x: 48, y: 24, size: 8, color: rgb(0.35, 0.35, 0.35) });
    return page;
  };
  for (const [index, section] of sections.entries()) {
    onProgress(`正在排版 Q${section.number}（${index + 1}/${sections.length}）`);
    const element = elements.get(section.id);
    if (!element) throw new Error("答案渲染未完成，请重试。");
    await readyForCapture(element);
    const region = regions[section.id];
    if (element.offsetHeight > 12000) throw new Error(`Q${section.number} 答案过长，无法可靠导出。`);
    const canvas = await captureAnswer(element, fontEmbedCSS);
    const scale = canvas.width / region.width;
    const fullHeight = canvas.height / scale;
    let from = 0;
    const original = pdf.getPage(region.page_number - 1);
    const firstEnd = findRasterBreak(canvas, 0, Math.max(0, region.height - (fullHeight > region.height ? 22 : 0)) * scale);
    if (firstEnd > 0) {
      const image = await pdf.embedPng(await pngSlice(canvas, 0, firstEnd));
      original.drawImage(image, pdfImagePosition(original, {
        page: region.page_number, x: region.x, y: region.y, width: region.width, height: firstEnd / scale,
      }));
      from = firstEnd;
    }
    if (from < canvas.height) {
      const continuation = pdf.getPageCount() + 1;
      const label = section.anchor === "whole" ? "" : ` ${section.anchor}`;
      const notePosition = pdfImagePosition(original, {
        page: region.page_number, x: region.x, y: region.y + region.height - 16, width: region.width, height: 12,
      });
      // Plain ASCII footer uses an embedded standard font and survives text extraction.
      original.drawText(`See PDF p. ${continuation}`, {
        ...notePosition, size: 9, color: rgb(0.05, 0.2, 0.55),
      });
      while (from < canvas.height) {
        const page = addPage(`Q${section.number}${label} — continued from original page ${region.page_number}`, region.width);
        const end = findRasterBreak(canvas, from, 724 * scale);
        if (end === from) throw new Error(`Q${section.number} 存在超过一页的连续公式或图形，请先调整答案。`);
        const image = await pdf.embedPng(await pngSlice(canvas, from, end));
        page.drawImage(image, { x: 48, y: 841.89 - 60 - (end - from) / scale, width: region.width, height: (end - from) / scale });
        from = end;
      }
    }
    for (const [diagramIndex, diagram] of section.diagrams.entries()) {
      if (!diagram.source) continue;
      const node = elements.get(`${section.id}:diagram:${diagramIndex}`);
      const sourcePage = layout.pages[diagram.source.page_number - 1];
      if (!node || !sourcePage || !section.sourcePages.includes(diagram.source.page_number)) {
        throw new Error(`Q${section.number} 原图定位信息不完整。`);
      }
      const [x, y, width, height] = diagram.view_box;
      const xScale = sourcePage.width / diagram.source.width;
      const yScale = sourcePage.height / diagram.source.height;
      const placement = { page: diagram.source.page_number, x: x * xScale, y: y * yScale, width: width * xScale, height: height * yScale };
      const overlay = await captureAnswer(node, fontEmbedCSS);
      const image = await pdf.embedPng(overlay.toDataURL("image/png"));
      const page = pdf.getPage(placement.page - 1);
      page.drawImage(image, pdfImagePosition(page, placement));
    }
  }
  const incomplete = job.questions.filter((q) => !q.skipped_by_strategy && (q.status !== "completed" || q.error || !q.answer_markdown));
  if (incomplete.length) {
    let page = addPage("Incomplete answer record — unanswered questions", 499);
    let y = 770;
    for (const question of incomplete) {
      if (y < 70) { page = addPage("Incomplete answer record — continued", 499); y = 770; }
      page.drawText(`Q${question.number}: no completed answer; original page(s) ${question.source_pages.join(", ") || "unknown"}`, { x: 48, y, size: 11 });
      y -= 24;
    }
  }
  onProgress("正在生成 PDF 文件");
  return new Uint8Array(await pdf.save());
}
