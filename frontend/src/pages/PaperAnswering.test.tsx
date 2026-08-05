import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { PaperAnswering } from "./PaperAnswering";

describe("PaperAnswering", () => {
  test("accepts a supported paper through drag and drop", () => {
    render(<PaperAnswering enabled={false} subject={null} />);
    const dropZone = screen.getByText("选择或拖入一份试卷").closest("label");
    const paper = new File(["# Question 1"], "paper.md", { type: "text/markdown" });

    fireEvent.drop(dropZone!, { dataTransfer: { files: [paper] } });

    expect(screen.getByText("paper.md")).toBeInTheDocument();
  });
});
