import { render } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { InlineMarkdown, Markdown } from "./components/Markdown";

describe("Markdown math", () => {
  test("renders standard LaTeX delimiters while preserving code examples", () => {
    const source = String.raw`Inline \(x^2+1\).

\[
\frac{1}{2}
\]

| expression |
| --- |
| \(u_{n+1}=u_n-9\) |
` + "\nCode: `\\(not_math\\)`\n";
    const { container } = render(
      <div>
        <Markdown>{source}</Markdown>
        <strong><InlineMarkdown>{String.raw`Rule: \(y=f(x)\)`}</InlineMarkdown></strong>
      </div>,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(4);
    expect(container.querySelector(".katex-display")).toBeInTheDocument();
    expect(container.querySelector("code")?.textContent).toBe(String.raw`\(not_math\)`);
    expect(container.querySelector("strong > p")).not.toBeInTheDocument();
  });

  test("keeps currency amounts as prose without disabling dollar-delimited math", () => {
    const { container } = render(
      <Markdown>
        {"Mexico spent $1,227 per person; the range is $85-70=15$ years."}
      </Markdown>,
    );

    expect(container).toHaveTextContent("Mexico spent $1,227 per person");
    expect(container.querySelectorAll(".katex")).toHaveLength(1);
    expect(container.querySelector(".katex")?.textContent).toContain("85");
  });

  test("preserves formulas that start with a number and variable", () => {
    const { container } = render(
      <Markdown>{"Solve $2 x + 1 = 7$ while keeping $2 million as prose."}</Markdown>,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(1);
    expect(container.querySelector(".katex")?.textContent).toContain("2x+1=7");
    expect(container).toHaveTextContent("$2 million as prose");
  });

  test("renders escaped currency inside dollar-delimited calculations", () => {
    const { container } = render(
      <Markdown>{String.raw`Range: $\$11,859-\$1,227=\$10,632$.`}</Markdown>,
    );

    expect(container.querySelector(".katex-error")).not.toBeInTheDocument();
    expect(container).toHaveTextContent("USD 11,859");
    expect(container).toHaveTextContent("USD 10,632");
  });
});
