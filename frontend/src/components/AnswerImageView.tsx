import { Expand, Shrink } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { backendResourceUrl } from "../lib/api";
import type { AnswerImage } from "../types";

export function AnswerImageView({ image }: { image: AnswerImage }) {
  const id = useId().replaceAll(":", "");
  const titleId = `answer-image-title-${id}`;
  const [expanded, setExpanded] = useState(false);

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

  return (
    <figure
      aria-labelledby={titleId}
      className={`answer-diagram answer-image${expanded ? " is-expanded" : ""}`}
    >
      <div className="answer-diagram-header">
        <div>
          <strong id={titleId}>{image.title}</strong>
          <span>GPT Image 生成图片 · 请核对内容准确性</span>
        </div>
        <div
          aria-label="图片查看控制"
          className="answer-diagram-controls"
          role="group"
        >
          <button
            aria-label={expanded ? "退出全屏查看图片" : "全屏查看图片"}
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
        <div className="answer-diagram-canvas">
          <img
            alt={image.title}
            height={image.height}
            loading="lazy"
            src={backendResourceUrl(image.content_url)}
            width={image.width}
          />
        </div>
      </div>
      {image.caption && <figcaption>{image.caption}</figcaption>}
    </figure>
  );
}
