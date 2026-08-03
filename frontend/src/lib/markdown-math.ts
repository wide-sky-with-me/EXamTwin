type Fence = {
  character: "`" | "~";
  length: number;
};

function fenceAtLineStart(line: string): Fence | null {
  const match = /^ {0,3}(`{3,}|~{3,})/.exec(line);
  if (!match) return null;
  return {
    character: match[1][0] as Fence["character"],
    length: match[1].length,
  };
}

function closesFence(line: string, fence: Fence) {
  const match = /^ {0,3}(`+|~+)/.exec(line);
  if (!match || match[1][0] !== fence.character || match[1].length < fence.length) {
    return false;
  }
  return /^[ \t]*(?:\n)?$/.test(line.slice(match[0].length));
}

function normalizeDelimiters(value: string) {
  return value
    .replace(
      /(?<!\\)\\\[([\s\S]*?)(?<!\\)\\\]/g,
      (_match, math: string) => `\n\n$$\n${math.trim()}\n$$\n\n`,
    )
    .replace(
      /(?<!\\)\\\(([^\n]*?)(?<!\\)\\\)/g,
      (_match, math: string) => `$${math}$`,
    );
}

function normalizeOutsideCodeSpans(value: string) {
  let output = "";
  let cursor = 0;
  let searchFrom = 0;

  while (searchFrom < value.length) {
    const opening = value.indexOf("`", searchFrom);
    if (opening < 0) break;

    let openingEnd = opening;
    while (value[openingEnd] === "`") openingEnd += 1;
    const tickCount = openingEnd - opening;
    let closing = openingEnd;

    while (closing < value.length) {
      closing = value.indexOf("`", closing);
      if (closing < 0) break;
      let closingEnd = closing;
      while (value[closingEnd] === "`") closingEnd += 1;
      if (closingEnd - closing === tickCount) {
        output += normalizeDelimiters(value.slice(cursor, opening));
        output += value.slice(opening, closingEnd);
        cursor = closingEnd;
        searchFrom = closingEnd;
        break;
      }
      closing = closingEnd;
    }

    if (closing < 0) {
      searchFrom = openingEnd;
    }
  }

  return output + normalizeDelimiters(value.slice(cursor));
}

/** Normalize common model/PDF LaTeX delimiters without touching Markdown code. */
export function canonicalizeMarkdownMath(markdown: string) {
  const lines = markdown.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  let fence: Fence | null = null;
  let prose = "";
  let output = "";

  const flushProse = () => {
    output += normalizeOutsideCodeSpans(prose);
    prose = "";
  };

  for (const line of lines) {
    if (fence) {
      output += line;
      if (closesFence(line, fence)) fence = null;
      continue;
    }

    const openingFence = fenceAtLineStart(line);
    if (openingFence) {
      flushProse();
      fence = openingFence;
      output += line;
      continue;
    }

    if (/^(?: {4}|\t)/.test(line)) {
      flushProse();
      output += line;
      continue;
    }
    prose += line;
  }

  flushProse();
  return output;
}
