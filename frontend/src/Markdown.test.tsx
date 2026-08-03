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
});
