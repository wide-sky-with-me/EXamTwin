import { Alert, Button, Checkbox, InputNumber, Modal, Select, Space, Spin } from "antd";
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { apiClient, backendResourceUrl, isBackendResourcePath, subjectHeaders, unwrapApi } from "../lib/api";
import {
  answerSections, createAnswerPdf, suggestedRegion, validateRegions,
  type AnswerPdfLayout, type AnswerRegion, type AnswerSection,
} from "../lib/answer-pdf";
import type { PaperJobResult } from "../types";
import { PrintableAnswerDiagram } from "./AnswerDiagramView";
import { InlineMarkdown, Markdown } from "./Markdown";
import "./paper-answer-pdf.css";

function SectionContent({ section, subjectId, jobId }: { section: AnswerSection; subjectId: string; jobId: string }) {
  const artifacts = [
    ...section.diagrams.filter((d) => !d.source).map((d, i) => ({
      order: d.answer_order ?? 100 + i, key: `d-${i}`,
      node: <PrintableAnswerDiagram diagram={d} subjectId={subjectId} jobId={jobId} />,
    })),
    ...section.images.map((image, i) => ({
      order: image.answer_order ?? 200 + i, key: `i-${i}`,
      node: <figure><img alt={image.title} src={backendResourceUrl(image.content_url, subjectId)} /><figcaption>{image.caption}</figcaption></figure>,
    })),
  ].sort((a, b) => a.order - b.order);
  return <>
    <Markdown components={{ img: ({ src, alt }) => isBackendResourcePath(typeof src === "string" ? src : undefined)
      ? <img src={backendResourceUrl(src as string, subjectId)} alt={alt ?? "答案图片"} />
      : <span data-pdf-missing-image>［答案图片地址不可用于导出］</span> }}>{section.markdown}</Markdown>
    {artifacts.map((a) => <div key={a.key}>{a.node}</div>)}
    {section.diagrams.filter((d) => d.source).map((diagram, index) => <div key={`source-caption-${index}`}>
      {diagram.legend.map((entry, i) => <p key={i}><InlineMarkdown>{entry.label}</InlineMarkdown></p>)}
      {diagram.caption && <p><InlineMarkdown>{diagram.caption}</InlineMarkdown></p>}
    </div>)}
  </>;
}

export function PaperAnswerPdf({ job, subjectId, onClose }: {
  job: PaperJobResult; subjectId: string; onClose: () => void;
}) {
  // Parent mounts by job ID; the export owns one frozen answer snapshot.
  const [snapshot] = useState(job);
  const sections = useMemo(() => answerSections(snapshot), [snapshot]);
  const [layout, setLayout] = useState<AnswerPdfLayout | null>(null);
  const [regions, setRegions] = useState<Record<string, AnswerRegion>>({});
  const [selectedId, setSelectedId] = useState(sections[0]?.id ?? "");
  const [pageNumber, setPageNumber] = useState(sections[0]?.sourcePages[0] ?? 1);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [checked, setChecked] = useState(false);
  const [selectingRegion, setSelectingRegion] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loadedPage, setLoadedPage] = useState(0);
  const elements = useRef(new Map<string, HTMLElement>());
  const pageRef = useRef<HTMLDivElement>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const mounted = useRef(true);
  const selected = sections.find((s) => s.id === selectedId);
  const region = regions[selectedId];
  const page = layout?.pages[pageNumber - 1];
  const incomplete = snapshot.questions.filter((q) => !q.skipped_by_strategy && (q.status !== "completed" || q.error || !q.answer_markdown)).length;

  useEffect(() => {
    const controller = new AbortController();
    void unwrapApi(apiClient.GET("/api/v1/papers/jobs/{job_id}/answer-pdf/layout", {
      headers: subjectHeaders(subjectId), params: { path: { job_id: snapshot.job_id } }, signal: controller.signal,
    })).then((result) => {
      if (controller.signal.aborted) return;
      setLayout(result);
      const suggested: Record<string, AnswerRegion> = {};
      for (const section of sections) {
        const match = suggestedRegion(section, result);
        if (match) suggested[section.id] = match;
      }
      setRegions(suggested);
      if (sections[0] && suggested[sections[0].id]) setPageNumber(suggested[sections[0].id].page_number);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "无法读取原卷布局。");
    });
    return () => controller.abort();
  }, [snapshot.job_id, subjectId, sections]);

  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  function changeRegion(value: AnswerRegion) {
    setRegions((current) => ({ ...current, [selectedId]: value }));
    setChecked(false);
    setPdfUrl(null);
    setError(null);
    setPageNumber(value.page_number);
  }

  function point(event: PointerEvent<HTMLDivElement>) {
    const bounds = pageRef.current?.getBoundingClientRect();
    if (!bounds || !page) return null;
    return {
      x: Math.max(0, Math.min(page.width, (event.clientX - bounds.left) * page.width / bounds.width)),
      y: Math.max(0, Math.min(page.height, (event.clientY - bounds.top) * page.height / bounds.height)),
    };
  }

  function drag(event: PointerEvent<HTMLDivElement>) {
    const start = dragStart.current;
    const end = point(event);
    if (!start || !end || !selected) return;
    changeRegion({ question_position: selected.position, answer_anchor: selected.anchor, page_number: pageNumber,
      x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width: Math.abs(end.x - start.x), height: Math.abs(end.y - start.y) });
  }

  async function generate() {
    if (!layout || busy || !checked) return;
    try {
      validateRegions(sections, regions, layout);
      setError(null);
      setBusy("正在读取原试卷");
      const response = await fetch(backendResourceUrl(`/papers/jobs/${snapshot.job_id}/source`, subjectId));
      if (!response.ok) throw new Error("无法读取原试卷，请检查源文件是否仍可用。");
      const result = await createAnswerPdf({
        source: await response.arrayBuffer(), layout, job: snapshot, sections, regions,
        elements: elements.current, onProgress: setBusy,
      });
      if (mounted.current) setPdfUrl(URL.createObjectURL(new Blob([result], { type: "application/pdf" })));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "PDF 导出失败，请重试。");
    } finally { setBusy(""); }
  }

  const readyCount = sections.filter((s) => regions[s.id]).length;
  return (
    <Modal open title="导出原卷作答 PDF" width={1180} footer={null} onCancel={onClose}
      closable={!busy} mask={{ closable: !busy }} keyboard={!busy}
      rootClassName="app-viewport-dialog answer-pdf-modal">
      <p>核对每个答题区后生成预览。文字按清晰字号排版，写不下的内容自动续页，并在原答题区标明页码。</p>
      {snapshot.strategy_plan && <Alert type="info" showIcon title={`目标 ${snapshot.strategy_plan.request.target_score} 分的策略答卷：未选小题保留空白；预期得分不代表实际评分。`} />}
      {incomplete > 0 && <Alert type="warning" showIcon title={`这是部分作答：${incomplete} 题尚无完整答案，导出文件会附未完成题目清单。`} />}
      {error && <Alert type="error" showIcon title={error} />}
      {!layout && !error && <Spin description="正在识别原卷答题区" />}
      {layout && !pdfUrl && <>
        <div className="answer-pdf-toolbar">
          <label>答案
            <Select aria-label="选择要放置的答案" value={selectedId} disabled={!!busy}
              options={sections.map((s) => ({ value: s.id, label: `Q${s.number} ${s.anchor === "whole" ? "" : s.anchor}${regions[s.id] ? " · 已定位" : " · 待框选"}` }))}
              onChange={(id) => {
                setSelectedId(id);
                setPageNumber(regions[id]?.page_number ?? sections.find((s) => s.id === id)?.sourcePages[0] ?? 1);
              }} />
          </label>
          <label>原卷页
            <Select aria-label="选择原卷页" value={pageNumber} disabled={!!busy}
              options={(selected?.sourcePages ?? []).map((p) => ({ value: p, label: `第 ${p} 页` }))}
              onChange={setPageNumber} />
          </label>
          <span>{readyCount}/{sections.length} 个答案已有区域</span>
          <Button disabled={!!busy || loadedPage !== pageNumber} type={selectingRegion ? "primary" : "default"}
            onClick={() => setSelectingRegion((value) => !value)}>{selectingRegion ? "取消框选" : "框选答题区"}</Button>
        </div>
        <div className="answer-pdf-editor">
          <div className="answer-pdf-source-scroll">
            {page && <div className={`answer-pdf-source${selectingRegion ? " is-selecting" : ""}`} ref={pageRef}
              aria-label="原卷答题区域，拖动框选" style={{ aspectRatio: `${page.width}/${page.height}` }}
              onPointerDown={(event) => {
                if (!selectingRegion || busy || loadedPage !== pageNumber || event.button !== 0) return;
                dragStart.current = point(event);
                event.currentTarget.setPointerCapture(event.pointerId);
              }}
              onPointerMove={drag} onPointerUp={(event) => { drag(event); dragStart.current = null; setSelectingRegion(false); }}
              onPointerCancel={() => { dragStart.current = null; }}>
              <img draggable={false} alt={`原卷第 ${pageNumber} 页`} key={pageNumber}
                onLoad={() => setLoadedPage(pageNumber)} onError={() => { setLoadedPage(0); setError("原卷页图加载失败，不能核对答题区。"); }}
                src={backendResourceUrl(`/papers/jobs/${snapshot.job_id}/source/pages/${pageNumber}`, subjectId)} />
              {Object.entries(regions).filter(([, r]) => r.page_number === pageNumber).map(([id, r]) => (
                <div key={id} className={`answer-pdf-region${id === selectedId ? " is-selected" : ""}`}
                  style={{ left: `${r.x / page.width * 100}%`, top: `${r.y / page.height * 100}%`, width: `${r.width / page.width * 100}%`, height: `${r.height / page.height * 100}%` }}>
                  <span>{(() => { const s = sections.find((item) => item.id === id); return `Q${s?.number} ${s?.anchor === "whole" ? "" : s?.anchor}`; })()}</span>
                </div>
              ))}
            </div>}
          </div>
          <div className="answer-pdf-controls">
            <p>{region ? "点击“框选答题区”后可重新框选，也可输入位置。请避开题干、原图与其他答案。" : "此答案需要手动定位。点击“框选答题区”后在原卷拖出区域；只放续页标注时也需留出区域。"}</p>
            <Button disabled={!!busy || !selected || !page} onClick={() => {
              if (!selected || !page) return;
              changeRegion(suggestedRegion(selected, layout) ?? {
                question_position: selected.position, answer_anchor: selected.anchor, page_number: pageNumber,
                x: 48, y: 100, width: Math.min(420, page.width - 96), height: 24,
              });
            }}>{region ? "恢复建议位置" : "用数值设置位置"}</Button>
            {region && <p>当前答题区位于原卷第 {region.page_number} 页。</p>}
            {region && <div className="answer-pdf-fields">
              {(["x", "y", "width", "height"] as const).map((key, index) => <label key={key}>
                {["左边距", "上边距", "宽度", "高度"][index]}（pt）
                <InputNumber aria-label={["答题区左边距", "答题区上边距", "答题区宽度", "答题区高度"][index]}
                  min={0} precision={1} value={region[key]} disabled={!!busy}
                  onChange={(value) => { if (value !== null) changeRegion({ ...region, [key]: value }); }} />
              </label>)}
            </div>}
            <div className="answer-pdf-answer-preview">
              <strong>待写入的答案</strong>
              {selected && <div className="answer-pdf-ink"><SectionContent section={selected} subjectId={subjectId} jobId={snapshot.job_id} /></div>}
              {selected?.diagrams.some((d) => d.source) && <p>已校准图形将直接叠绘到原卷对应位置。</p>}
            </div>
          </div>
        </div>
        <p className="answer-pdf-hint">{layout.warnings.join(" ")} 位置调整仅用于本次导出，关闭后需重新定位。</p>
        <Checkbox checked={checked} disabled={!!busy || readyCount !== sections.length || loadedPage !== pageNumber}
          onChange={(event) => setChecked(event.target.checked)}>我已核对各题区域，确认不会遮挡题干或原图</Checkbox>
      </>}
      {pdfUrl && <iframe className="answer-pdf-document" src={pdfUrl} title="已作答原卷 PDF 预览" />}
      <Space wrap className="answer-pdf-actions">
        {pdfUrl ? <>
          <Button onClick={() => { setPdfUrl(null); setChecked(false); }}>返回调整位置</Button>
          <Button type="primary" href={pdfUrl} download={`${snapshot.filename.replace(/\.pdf$/i, "")}-${incomplete ? "partial-" : ""}answered.pdf`}>下载已作答 PDF</Button>
        </> : <Button type="primary" loading={!!busy} disabled={!layout || !checked || !sections.length}
          onClick={() => void generate()}>{busy || "生成 PDF 预览"}</Button>}
        <Button disabled={!!busy} onClick={onClose}>关闭</Button>
      </Space>
      <div className="answer-pdf-capture" aria-hidden="true">
        {sections.map((section) => <div key={section.id}>
          <div className="answer-pdf-ink" style={{ width: regions[section.id]?.width ?? 420 }}
            ref={(node) => { if (node) elements.current.set(section.id, node); else elements.current.delete(section.id); }}>
            <SectionContent section={section} subjectId={subjectId} jobId={snapshot.job_id} />
          </div>
          {section.diagrams.map((diagram, index) => diagram.source && <div key={index}
            className="answer-pdf-ink answer-pdf-overlay" style={{ width: diagram.view_box[2], height: diagram.view_box[3] }}
            ref={(node) => { const key = `${section.id}:diagram:${index}`; if (node) elements.current.set(key, node); else elements.current.delete(key); }}>
            <PrintableAnswerDiagram diagram={diagram} subjectId={subjectId} jobId={snapshot.job_id} overlayOnly />
          </div>)}
        </div>)}
      </div>
    </Modal>
  );
}
