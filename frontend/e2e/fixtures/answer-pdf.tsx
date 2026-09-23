import { createRoot } from "react-dom/client";
import { ConfigProvider } from "antd";
import { PaperAnswerPdf } from "../../src/components/PaperAnswerPdf";
import type { PaperJobResult } from "../../src/types";
import "katex/dist/katex.min.css";
import "../../src/styles.css";

const response = await fetch("/export-fixture.json");
const job = await response.json() as PaperJobResult;
createRoot(document.getElementById("root")!).render(
  <ConfigProvider><PaperAnswerPdf job={job} subjectId="oxfordaqa-mathematics-9660" onClose={() => {}} /></ConfigProvider>,
);
