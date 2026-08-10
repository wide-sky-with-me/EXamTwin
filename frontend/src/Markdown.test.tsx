import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { InlineMarkdown, Markdown, QuestionMarkdown } from "./components/Markdown";

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

  test("renders bare model LaTeX only when explicitly enabled", () => {
    const { container } = render(
      <Markdown normalizeBareLatex>
        {String.raw`Evidence: "a=\frac{5.2}{0.55}". Result: \boxed{9.45\ \mathrm{m\,s^{-2}}}. Keep ` + "`\\command`" + " in code."}
      </Markdown>,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(2);
    expect(container.querySelector("code")?.textContent).toBe(String.raw`\command`);
  });

  test("renders mixed bare Q4 evidence without broken LaTeX", () => {
    const samples = [
      String.raw`d=\frac{1645(6.5)\sin19^\circ}{219(9.8)}=1.6220005\ldots\text{ m}, hence \boxed{d=1.622\text{ m}}.`,
      String.raw`(1645\sin19^\circ)(6.5) and (219g)d.`,
      String.raw`T_A'\cos46^\circ=T_B'\cos19^\circ, followed by the limiting condition T_A'\leq3000.`,
      String.raw`\frac{T_A'}{T_B'}=\frac{\cos19^\circ}{\cos46^\circ}>1, so S_A always has the greater tension.`,
    ];
    const { container } = render(
      <div>
        {samples.map((sample) => (
          <Markdown key={sample} normalizeBareLatex>{sample}</Markdown>
        ))}
      </div>,
    );

    expect(container.querySelector(".katex-error")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(7);
    expect(container).toHaveTextContent("hence");
    expect(container).toHaveTextContent("followed by the limiting condition");
    expect(container).toHaveTextContent("so S_A always has the greater tension");
  });

  test("keeps extracted question images inline with surrounding text", () => {
    const imageUrl = (
      "/api/v1/papers/jobs/job-1/question-images/"
      + `p0001-${"a".repeat(64)}.png`
    );
    const { container } = render(
      <QuestionMarkdown>
        {`Before diagram.\n\n![Force diagram](${imageUrl})\n\nAfter diagram.`}
      </QuestionMarkdown>,
    );

    const image = screen.getByRole("img", { name: "Force diagram" });
    expect(image).toHaveAttribute("src", imageUrl);
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveClass("question-source-image");
    expect(
      Array.from(container.children).map((node) =>
        node.querySelector("img")?.getAttribute("alt") ?? node.textContent),
    ).toEqual(["Before diagram.", "Force diagram", "After diagram."]);
  });
});
