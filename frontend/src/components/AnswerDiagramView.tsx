import {
  Expand,
  Minus,
  Plus,
  RotateCcw,
  Shrink,
} from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import rehypeKatex from "rehype-katex";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import { canonicalizeMarkdownMath } from "../lib/markdown-math";
import type {
  AnswerDiagram,
  DiagramElement,
  DiagramTone,
} from "../types";

const TONES: DiagramTone[] = [
  "default",
  "primary",
  "secondary",
  "tertiary",
  "muted",
];

const TOOL_LABELS: Record<NonNullable<AnswerDiagram["tool_name"]>, string> = {
  math_plot: "函数与坐标绘图",
  math_diagram: "几何与示意绘图",
};

function hasMathNotation(value: string) {
  return /(?:^|[^\\])\$[^$]+\$|\\\(.+?\\\)|\\\[.+?\\\]/s.test(value);
}

function DiagramMathLabel({
  element,
  className,
}: {
  element: DiagramElement;
  className: string;
}) {
  const x = element.x ?? 0;
  const y = element.y ?? 0;
  const text = element.text ?? "";
  const mathRef = useRef<HTMLDivElement>(null);
  const [mathScale, setMathScale] = useState(1);

  useLayoutEffect(() => {
    const content = mathRef.current;
    if (!content || !hasMathNotation(text)) {
      setMathScale(1);
      return;
    }
    const availableWidth = 182;
    setMathScale(
      content.scrollWidth > availableWidth
        ? availableWidth / content.scrollWidth
        : 1,
    );
  }, [text]);

  if (!hasMathNotation(text)) {
    return (
      <text x={x} y={y} className={className}>
        {text}
      </text>
    );
  }

  return (
    <foreignObject
      className={`diagram-math-label ${className}`}
      height={52}
      overflow="visible"
      width={190}
      x={x}
      y={y - 29}
    >
      <div
        ref={mathRef}
        style={
          mathScale < 1
            ? {
                transform: `scale(${mathScale})`,
                transformOrigin: "left center",
              }
            : undefined
        }
      >
        <ReactMarkdown
          remarkPlugins={[remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{
            p({ children }) {
              return <span>{children}</span>;
            },
          }}
        >
          {canonicalizeMarkdownMath(text)}
        </ReactMarkdown>
      </div>
    </foreignObject>
  );
}

function DiagramScene({
  diagram,
  titleId,
  descriptionId,
}: {
  diagram: AnswerDiagram;
  titleId: string;
  descriptionId: string;
}) {
  const markerPrefix = `answer-arrow-${useId().replaceAll(":", "")}`;
  const [minX, minY, width, height] = diagram.view_box;
  const points = (value: [number, number][]) =>
    value.map(([x, y]) => `${x},${y}`).join(" ");
  const tone = (element: DiagramElement): DiagramTone =>
    element.tone ?? "default";
  const elementClass = (element: DiagramElement) =>
    [
      element.dashed ? "dashed" : "",
      element.emphasis ? "emphasis" : "",
      `fill-${element.fill}`,
      `tone-${tone(element)}`,
    ]
      .filter(Boolean)
      .join(" ");
  const markers = (element: DiagramElement) => ({
    markerStart: element.arrow_start
      ? `url(#${markerPrefix}-${tone(element)})`
      : undefined,
    markerEnd: element.arrow_end
      ? `url(#${markerPrefix}-${tone(element)})`
      : undefined,
  });

  return (
    <svg
      aria-labelledby={`${titleId} ${descriptionId}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      viewBox={`${minX} ${minY} ${width} ${height}`}
    >
      <title>{diagram.title}</title>
      <desc id={descriptionId}>
        {diagram.caption ||
          `由答题 Agent 创建的${TOOL_LABELS[diagram.tool_name ?? "math_diagram"]}。`}
      </desc>
      <defs>
        {TONES.map((markerTone) => (
          <marker
            id={`${markerPrefix}-${markerTone}`}
            key={markerTone}
            markerHeight="7"
            markerWidth="7"
            orient="auto-start-reverse"
            refX="8"
            refY="5"
            viewBox="0 0 10 10"
          >
            <path
              className={`arrow-head tone-${markerTone}`}
              d="M 0 0 L 10 5 L 0 10 z"
            />
          </marker>
        ))}
      </defs>
      {diagram.elements.map((element, elementIndex) => {
        const common = {
          className: elementClass(element),
          vectorEffect: "non-scaling-stroke" as const,
          ...markers(element),
        };
        const key = `${element.kind}-${elementIndex}`;
        switch (element.kind) {
          case "line":
            return (
              <line
                key={key}
                x1={element.x1}
                x2={element.x2}
                y1={element.y1}
                y2={element.y2}
                {...common}
              />
            );
          case "polyline":
            return (
              <polyline
                key={key}
                points={points(element.points)}
                {...common}
              />
            );
          case "polygon":
            return (
              <polygon
                key={key}
                points={points(element.points)}
                {...common}
              />
            );
          case "circle":
            return (
              <circle
                key={key}
                cx={element.cx}
                cy={element.cy}
                r={element.r}
                {...common}
              />
            );
          case "ellipse":
            return (
              <ellipse
                key={key}
                cx={element.cx}
                cy={element.cy}
                rx={element.rx}
                ry={element.ry}
                {...common}
              />
            );
          case "path":
            return <path key={key} d={element.d} {...common} />;
          case "point":
            return (
              <circle
                key={key}
                cx={element.x}
                cy={element.y}
                r={element.emphasis ? 5 : 3.5}
                {...common}
              />
            );
          case "text":
            return (
              <DiagramMathLabel
                className={elementClass(element)}
                element={element}
                key={key}
              />
            );
        }
      })}
    </svg>
  );
}

export function AnswerDiagramView({ diagram }: { diagram: AnswerDiagram }) {
  const id = useId().replaceAll(":", "");
  const titleId = `answer-diagram-title-${id}`;
  const descriptionId = `answer-diagram-description-${id}`;
  const [zoom, setZoom] = useState(1);
  const [expanded, setExpanded] = useState(false);
  const toolName = diagram.tool_name ?? "math_diagram";

  useEffect(() => {
    if (!expanded) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [expanded]);

  const updateZoom = (next: number) => {
    setZoom(Math.min(2.5, Math.max(1, Number(next.toFixed(2)))));
  };

  return (
    <figure
      aria-labelledby={titleId}
      className={`answer-diagram${expanded ? " is-expanded" : ""}`}
    >
      <div className="answer-diagram-header">
        <div>
          <strong id={titleId}>{diagram.title}</strong>
          <span>{TOOL_LABELS[toolName]} · 安全矢量图</span>
        </div>
        <div
          aria-label="图形查看控制"
          className="answer-diagram-controls"
          role="group"
        >
          <button
            aria-label="缩小图形"
            disabled={zoom <= 1}
            onClick={() => updateZoom(zoom - 0.25)}
            title="缩小"
            type="button"
          >
            <Minus size={15} />
          </button>
          <output aria-live="polite">{Math.round(zoom * 100)}%</output>
          <button
            aria-label="放大图形"
            disabled={zoom >= 2.5}
            onClick={() => updateZoom(zoom + 0.25)}
            title="放大"
            type="button"
          >
            <Plus size={15} />
          </button>
          <button
            aria-label="重置图形缩放"
            disabled={zoom === 1}
            onClick={() => setZoom(1)}
            title="重置缩放"
            type="button"
          >
            <RotateCcw size={14} />
          </button>
          <button
            aria-label={expanded ? "退出全屏查看" : "全屏查看图形"}
            aria-pressed={expanded}
            onClick={() => setExpanded((value) => !value)}
            title={expanded ? "退出全屏" : "全屏查看"}
            type="button"
          >
            {expanded ? <Shrink size={15} /> : <Expand size={15} />}
          </button>
        </div>
      </div>
      <div className="answer-diagram-viewport" tabIndex={0}>
        <div
          className="answer-diagram-canvas"
          style={{ width: `${zoom * 100}%` }}
        >
          <DiagramScene
            descriptionId={descriptionId}
            diagram={diagram}
            titleId={titleId}
          />
        </div>
      </div>
      {(diagram.legend ?? []).length > 0 && (
        <ul aria-label="图例" className="answer-diagram-legend">
          {(diagram.legend ?? []).map((item, index) => (
            <li key={`${item.label}-${index}`}>
              <i className={`tone-${item.tone}`} />
              <span>
                <ReactMarkdown
                  remarkPlugins={[remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={{
                    p({ children }) {
                      return <>{children}</>;
                    },
                  }}
                >
                  {canonicalizeMarkdownMath(item.label)}
                </ReactMarkdown>
              </span>
            </li>
          ))}
        </ul>
      )}
      {diagram.caption && <figcaption>{diagram.caption}</figcaption>}
    </figure>
  );
}
