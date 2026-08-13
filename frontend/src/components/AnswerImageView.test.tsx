import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import type { AnswerImage } from "../types";
import { AnswerImageView } from "./AnswerImageView";

const image: AnswerImage = {
  artifact_id: null,
  answer_anchor: null,
  answer_order: null,
  title: "Cell membrane illustration",
  caption: "A generated educational illustration.",
  tool_name: "image_generate",
  content_url: "/api/v1/answer-assets/0123456789abcdef0123456789abcdef.png",
  media_type: "image/png",
  width: 1024,
  height: 1024,
  generated: true,
};

describe("AnswerImageView", () => {
  test("renders a server asset with provenance and caption", () => {
    render(<AnswerImageView image={image} subjectId="test-subject" />);

    expect(screen.getByRole("img", { name: image.title })).toHaveAttribute(
      "src",
      "/api/v1/answer-assets/0123456789abcdef0123456789abcdef.png?subject=test-subject",
    );
    expect(screen.getByText(/GPT Image 生成图片/)).toBeInTheDocument();
    expect(screen.getByText(image.caption)).toBeInTheDocument();
  });

  test("supports fullscreen and Escape recovery", async () => {
    const user = userEvent.setup();
    const { container } = render(<AnswerImageView image={image} subjectId="test-subject" />);

    await user.click(screen.getByRole("button", { name: "全屏查看图片" }));
    expect(container.querySelector(".answer-image")).toHaveClass("is-expanded");
    expect(document.body.style.overflow).toBe("hidden");

    expect(screen.getByRole("dialog", { name: image.title })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退出全屏查看图片" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(container.querySelector(".answer-image")).not.toHaveClass("is-expanded");
    expect(screen.getByRole("button", { name: "全屏查看图片" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });
});
