import { Expand, Shrink } from "lucide-react";
import { useId, useState } from "react";
import { backendResourceUrl } from "../lib/api";
import { useModalFocus } from "../lib/use-modal-focus";
import type { AnswerImage } from "../types";
import { InlineMarkdown } from "./Markdown";

export function AnswerImageView({
  image,
  subjectId,
}: {
  image: AnswerImage;
  subjectId: string;
}) {
  const id = useId().replaceAll(":", "");
  const titleId = `answer-image-title-${id}`;
  const [expanded, setExpanded] = useState(false);
  const containerRef = useModalFocus(expanded, setExpanded);

  return (
    <figure
      aria-modal={expanded || undefined}
      aria-labelledby={titleId}
      className={`answer-diagram answer-image${expanded ? " is-expanded" : ""}`}
      ref={containerRef}
      role={expanded ? "dialog" : undefined}
      tabIndex={expanded ? -1 : undefined}
    >
      <div className="answer-diagram-header">
        <div>
          <strong id={titleId}><InlineMarkdown>{image.title}</InlineMarkdown></strong>
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
            data-modal-close={expanded ? "" : undefined}
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
            src={backendResourceUrl(image.content_url, subjectId)}
            width={image.width}
          />
        </div>
      </div>
      {image.caption && <figcaption><InlineMarkdown>{image.caption}</InlineMarkdown></figcaption>}
    </figure>
  );
}
