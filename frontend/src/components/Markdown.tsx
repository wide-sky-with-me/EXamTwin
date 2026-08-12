import "katex/dist/katex.min.css";

import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import { useState, type ComponentPropsWithoutRef, type SyntheticEvent } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { canonicalizeLooseMarkdownMath, canonicalizeMarkdownMath } from "../lib/markdown-math";
import { backendResourceUrl } from "../lib/api";

type HastNode = {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  value?: string;
  children?: HastNode[];
};

const tableInlineMathPattern = /\\\((.+?)\\\)|(?<!\\)\$([^$\n]+?)(?<!\\)\$/g;

function inlineTableMath(value: string): HastNode[] {
  const nodes: HastNode[] = [];
  let cursor = 0;

  for (const match of value.matchAll(tableInlineMathPattern)) {
    const start = match.index;
    if (start > cursor) {
      nodes.push({ type: "text", value: value.slice(cursor, start) });
    }
    nodes.push({
      type: "element",
      tagName: "span",
      properties: { className: ["math-inline"] },
      children: [{ type: "text", value: match[1] ?? match[2] ?? "" }],
    });
    cursor = start + match[0].length;
  }

  if (!nodes.length) return [{ type: "text", value }];
  if (cursor < value.length) {
    nodes.push({ type: "text", value: value.slice(cursor) });
  }
  return nodes;
}

function rehypeTableMath() {
  return (tree: HastNode) => {
    function visit(node: HastNode, insideCell = false) {
      const tagName = node.tagName?.toLowerCase();
      const nextInsideCell = insideCell || tagName === "td" || tagName === "th";
      if (!node.children || tagName === "code" || tagName === "pre" || tagName === "math") {
        return;
      }

      const children: HastNode[] = [];
      for (const child of node.children) {
        if (nextInsideCell && child.type === "text" && child.value) {
          children.push(...inlineTableMath(child.value));
        } else {
          visit(child, nextInsideCell);
          children.push(child);
        }
      }
      node.children = children;
    }

    visit(tree);
  };
}

const questionMarkPattern = /(\[\s*\d+\s+marks?\s*\])/gi;

function questionMarkNodes(value: string): HastNode[] {
  const nodes: HastNode[] = [];
  let cursor = 0;
  for (const match of value.matchAll(questionMarkPattern)) {
    const start = match.index;
    if (start > cursor) {
      nodes.push({ type: "text", value: value.slice(cursor, start) });
    }
    nodes.push({
      type: "element",
      tagName: "span",
      properties: { className: ["question-marks"] },
      children: [{ type: "text", value: match[0] }],
    });
    cursor = start + match[0].length;
  }
  if (!nodes.length) return [{ type: "text", value }];
  if (cursor < value.length) {
    nodes.push({ type: "text", value: value.slice(cursor) });
  }
  return nodes;
}

function rehypeQuestionMarks() {
  return (tree: HastNode) => {
    function visit(node: HastNode) {
      const tagName = node.tagName?.toLowerCase();
      if (!node.children || tagName === "code" || tagName === "pre" || tagName === "math") {
        return;
      }
      const children: HastNode[] = [];
      for (const child of node.children) {
        if (child.type === "text" && child.value) {
          children.push(...questionMarkNodes(child.value));
        } else {
          visit(child);
          children.push(child);
        }
      }
      node.children = children;
    }
    visit(tree);
  };
}

const markdownComponents: Components = {
  table({ node, ...props }) {
    void node;
    return (
      <div className="markdown-table-scroll" tabIndex={0}>
        <table {...props} />
      </div>
    );
  },
};

type QuestionSourceImageLayout = "pending" | "compact" | "figure" | "error";

function QuestionSourceImage({
  alt = "",
  className,
  onError,
  onLoad,
  src,
  ...props
}: ComponentPropsWithoutRef<"img">) {
  const [layout, setLayout] = useState<QuestionSourceImageLayout>("pending");

  function handleLoad(event: SyntheticEvent<HTMLImageElement>) {
    onLoad?.(event);
    const image = event.currentTarget;
    setLayout(
      image.naturalWidth <= 128 && image.naturalHeight <= 96
        ? "compact"
        : "figure",
    );
  }

  function handleError(event: SyntheticEvent<HTMLImageElement>) {
    onError?.(event);
    setLayout("error");
  }

  if (layout === "error") {
    return (
      <a className="question-source-image-error" href={src} rel="noreferrer" target="_blank">
        题目图片加载失败，点击单独打开
      </a>
    );
  }

  return (
    <img
      {...props}
      alt={alt}
      className={["question-source-image", `is-${layout}`, className]
        .filter(Boolean)
        .join(" ")}
      decoding="async"
      loading="lazy"
      onError={handleError}
      onLoad={handleLoad}
      src={src}
    />
  );
}

const questionMarkdownComponents: Components = {
  ...markdownComponents,
  img({ node, src, ...props }) {
    void node;
    const resolvedSrc = src?.startsWith("/api/v1/")
      ? backendResourceUrl(src)
      : src;
    return <QuestionSourceImage {...props} src={resolvedSrc} />;
  },
};

const inlineMarkdownComponents: Components = {
  ...markdownComponents,
  p({ children }) {
    return <>{children}</>;
  },
};

export function Markdown({
  children,
  components,
  normalizeBareLatex = false,
}: {
  children: string;
  components?: Components;
  normalizeBareLatex?: boolean;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeRaw, rehypeSanitize, rehypeTableMath, rehypeKatex]}
      components={{ ...markdownComponents, ...components }}
    >
      {normalizeBareLatex ? canonicalizeLooseMarkdownMath(children) : canonicalizeMarkdownMath(children)}
    </ReactMarkdown>
  );
}

export function InlineMarkdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeRaw, rehypeSanitize, rehypeTableMath, rehypeKatex]}
      components={inlineMarkdownComponents}
    >
      {canonicalizeMarkdownMath(children)}
    </ReactMarkdown>
  );
}

function normalizeQuestionMath(markdown: string) {
  return canonicalizeMarkdownMath(markdown).replace(
    /\$((?:\\begin\{(?:bmatrix|pmatrix|matrix|cases|aligned)\})[\s\S]*?(?:\\end\{(?:bmatrix|pmatrix|matrix|cases|aligned)\}))\$(?:\s*[.;:])?/g,
    (_match, math: string) => `\n\n$$\n${math}\n$$\n\n`,
  );
}

export function QuestionMarkdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[
        rehypeRaw,
        rehypeSanitize,
        rehypeQuestionMarks,
        rehypeTableMath,
        rehypeKatex,
      ]}
      components={questionMarkdownComponents}
    >
      {normalizeQuestionMath(children)}
    </ReactMarkdown>
  );
}
