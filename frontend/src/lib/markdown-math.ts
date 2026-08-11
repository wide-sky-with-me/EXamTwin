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

function normalizeDollarMathCurrency(value: string) {
  return value.replace(
    /(?<!\\)\$((?:\\\$|[^$\n])*)(?<!\\)\$/g,
    (match: string, math: string) =>
      math.includes("\\$") ? `$${math.replace(/\\\$/g, "\\text{USD }")}$` : match,
  );
}

function escapeCurrencyDollars(value: string) {
  return value.replace(
    /(?<!\\)\$(\d[\d,]*(?:\.\d+)?)/g,
    (match: string, amount: string, offset: number, source: string) => {
      const remainder = source.slice(offset + match.length);
      const closingOffset = remainder.search(/(?<!\\)\$/);
      if (closingOffset >= 0) {
        const candidate = source.slice(
          offset + 1,
          offset + match.length + closingOffset,
        );
        const startsWithNumberAndVariable =
          /^\d[\d,.]*\s*[A-Za-z](?![A-Za-z])/.test(candidate);
        if (startsWithNumberAndVariable || /[+\-*/=^_<>{}\\]/.test(candidate)) {
          return match;
        }
      }
      const afterAmount = remainder[0] ?? "";
      if (/[+\-*/=^_<>{}\\$]/.test(afterAmount)) return match;
      const followedByProse = /^\s+[A-Za-z]/.test(remainder);
      return amount.includes(",") || followedByProse ? `\\${match}` : match;
    },
  );
}

function normalizeDelimiters(value: string) {
  return escapeCurrencyDollars(normalizeDollarMathCurrency(value))
    .replace(
      /(?<!\\)\\\[([\s\S]*?)(?<!\\)\\\]/g,
      (_match, math: string) => `\n\n$$\n${math.trim()}\n$$\n\n`,
    )
    .replace(
      /(?<!\\)\\\(([^\n]*?)(?<!\\)\\\)/g,
      (_match, math: string) => `$${math}$`,
    );
}

const quotedBareLatexPattern = /(["“])([^"”\n]*\\[A-Za-z]+[^"”\n]*)(["”])/g;
const delimitedMathPattern = /(\$\$[\s\S]*?\$\$|\$[^$\n]+\$)/g;
const bareLatexCommandPattern = /\\[A-Za-z]+/g;

function replaceBareLatexTokens(value: string) {
  let output = "";
  let cursor = 0;
  bareLatexCommandPattern.lastIndex = 0;
  for (let match = bareLatexCommandPattern.exec(value); match; match = bareLatexCommandPattern.exec(value)) {
    if (match.index < cursor) continue;
    let start = match.index;
    while (start > cursor && !/[\s$"`]/.test(value[start - 1])) start -= 1;

    let end = start;
    let braceDepth = 0;
    while (end < value.length) {
      const character = value[end];
      if (character === "\\" && /\s/.test(value[end + 1] ?? "")) {
        end += 2;
        continue;
      }
      if (character === "{") braceDepth += 1;
      if (character === "}") braceDepth = Math.max(0, braceDepth - 1);
      if (braceDepth === 0 && /[\s$"`]/.test(character)) break;
      end += 1;
    }
    if (braceDepth !== 0) continue;
    output += `${value.slice(cursor, start)}$${value.slice(start, end)}$`;
    cursor = end;
    bareLatexCommandPattern.lastIndex = end;
  }
  return output + value.slice(cursor);
}

function normalizeBareLatex(value: string) {
  const quoted = value.replace(
    quotedBareLatexPattern,
    (match, opening: string, math: string, closing: string) =>
      math.includes("$") ? match : `${opening}$${math}$${closing}`,
  );
  return quoted
    .split(delimitedMathPattern)
    .map((segment, index) =>
      index % 2 === 1
        ? segment
        : replaceBareLatexTokens(segment))
    .join("");
}

function transformOutsideCodeSpans(value: string, transform: (value: string) => string) {
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
        output += transform(value.slice(cursor, opening));
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

  return output + transform(value.slice(cursor));
}

function transformMarkdownProse(markdown: string, transform: (value: string) => string) {
  const lines = markdown.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  let fence: Fence | null = null;
  let prose = "";
  let output = "";

  const flushProse = () => {
    output += transformOutsideCodeSpans(prose, transform);
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

/** Normalize common model/PDF LaTeX delimiters without touching Markdown code. */
export function canonicalizeMarkdownMath(markdown: string) {
  return transformMarkdownProse(markdown, normalizeDelimiters);
}

/** Also delimit bare model-generated LaTeX commands in prose. */
export function canonicalizeLooseMarkdownMath(markdown: string) {
  return transformMarkdownProse(canonicalizeMarkdownMath(markdown), normalizeBareLatex);
}
