import { createRoot } from "react-dom/client";
import { AnswerDiagramView } from "../../src/components/AnswerDiagramView";
import { Markdown } from "../../src/components/Markdown";
import type { AnswerDiagram } from "../../src/types";
import "../../src/styles.css";

const response = await fetch("/runtime-answer.json");
const answer = await response.json() as { question_number: string; answer_markdown: string; diagrams: AnswerDiagram[] };
createRoot(document.getElementById("root")!).render(
  <main style={{ maxWidth: 860, margin: "24px auto", padding: 24, background: "white" }}>
    <h1>Question {answer.question_number}</h1>
    <Markdown>{answer.answer_markdown}</Markdown>
    {answer.diagrams.map((diagram, index) => <AnswerDiagramView key={index} diagram={diagram} />)}
  </main>,
);
