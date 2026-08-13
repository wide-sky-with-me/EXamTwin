import { Fragment, type ReactNode } from "react";

import type { AnswerDiagram, AnswerImage } from "../types";
import { AnswerDiagramView } from "./AnswerDiagramView";
import { AnswerImageView } from "./AnswerImageView";

type ArtifactEntry = {
  answerAnchor: string | null;
  answerOrder: number | null;
  artifactId: string | null;
  fallbackOrder: number;
  kind: "diagram" | "image";
  value: AnswerDiagram | AnswerImage;
};

type Heading = {
  answerAnchor: string;
  start: number;
};

function answerHeadings(markdown: string): Heading[] {
  const headings: Heading[] = [];
  const lines = markdown.match(/.*(?:\r?\n|$)/g) ?? [];
  let offset = 0;
  let fence: "```" | "~~~" | null = null;
  for (const line of lines) {
    const fenceMatch = line.match(/^\s*(```|~~~)/);
    if (fenceMatch) {
      const marker = fenceMatch[1] as "```" | "~~~";
      fence = fence === marker ? null : fence ?? marker;
    } else if (fence === null) {
      const heading = line.match(/^###[ \t]+(.+?)[ \t]*(?:\r?\n)?$/);
      if (heading) headings.push({ answerAnchor: heading[1], start: offset });
    }
    offset += line.length;
  }
  return headings;
}

function artifactEntries(diagrams: AnswerDiagram[], images: AnswerImage[]): ArtifactEntry[] {
  const entries = [
    ...diagrams.map((value, index): ArtifactEntry => ({
      answerAnchor: value.answer_anchor,
      answerOrder: value.answer_order,
      artifactId: value.artifact_id,
      fallbackOrder: index,
      kind: "diagram",
      value,
    })),
    ...images.map((value, index): ArtifactEntry => ({
      answerAnchor: value.answer_anchor,
      answerOrder: value.answer_order,
      artifactId: value.artifact_id,
      fallbackOrder: diagrams.length + index,
      kind: "image",
      value,
    })),
  ];
  const seen = new Set<string>();
  return entries
    .filter((entry) => {
      if (!entry.artifactId) return true;
      if (seen.has(entry.artifactId)) return false;
      seen.add(entry.artifactId);
      return true;
    })
    .sort((left, right) => (
      (left.answerOrder ?? Number.MAX_SAFE_INTEGER)
      - (right.answerOrder ?? Number.MAX_SAFE_INTEGER)
      || left.fallbackOrder - right.fallbackOrder
    ));
}

function artifactKey(entry: ArtifactEntry) {
  return entry.artifactId ?? `legacy-${entry.kind}-${entry.fallbackOrder}`;
}

export function AnswerArtifactFlow({
  answerMarkdown,
  diagrams,
  images,
  subjectId,
  jobId,
  renderMarkdown,
}: {
  answerMarkdown: string;
  diagrams: AnswerDiagram[];
  images: AnswerImage[];
  subjectId: string;
  jobId?: string;
  renderMarkdown: (markdown: string, key: string) => ReactNode;
}) {
  const entries = artifactEntries(diagrams, images);
  if (entries.length === 0) return renderMarkdown(answerMarkdown, "answer-markdown");

  const headings = answerHeadings(answerMarkdown);
  const insertionPoints = new Map<string, number[]>();
  headings.forEach((heading, index) => {
    const end = headings[index + 1]?.start ?? answerMarkdown.length;
    const points = insertionPoints.get(heading.answerAnchor) ?? [];
    points.push(end);
    insertionPoints.set(heading.answerAnchor, points);
  });

  const artifactsByOffset = new Map<number, ArtifactEntry[]>();
  for (const entry of entries) {
    const candidates = entry.answerAnchor && entry.answerAnchor !== "whole"
      ? insertionPoints.get(entry.answerAnchor)
      : undefined;
    const offset = candidates?.length === 1 ? candidates[0] : answerMarkdown.length;
    const atOffset = artifactsByOffset.get(offset) ?? [];
    atOffset.push(entry);
    artifactsByOffset.set(offset, atOffset);
  }

  const offsets = [...artifactsByOffset.keys()].sort((left, right) => left - right);
  let cursor = 0;
  return (
    <div className="answer-artifact-flow">
      {offsets.map((offset, groupIndex) => {
        const markdown = answerMarkdown.slice(cursor, offset);
        cursor = offset;
        const group = artifactsByOffset.get(offset) ?? [];
        return (
          <Fragment key={`answer-artifacts-${offset}-${groupIndex}`}>
            {markdown && renderMarkdown(markdown, `answer-markdown-${groupIndex}`)}
            <div className="answer-diagrams" data-answer-anchor={group[0]?.answerAnchor ?? "fallback"}>
              {group.map((entry) => entry.kind === "diagram"
                ? (
                    <AnswerDiagramView
                      diagram={entry.value as AnswerDiagram}
                      subjectId={subjectId}
                      jobId={jobId}
                      key={artifactKey(entry)}
                    />
                  )
                : (
                    <AnswerImageView
                      image={entry.value as AnswerImage}
                      subjectId={subjectId}
                      key={artifactKey(entry)}
                    />
                  ))}
            </div>
          </Fragment>
        );
      })}
      {cursor < answerMarkdown.length
        && renderMarkdown(answerMarkdown.slice(cursor), "answer-markdown-tail")}
    </div>
  );
}
