import { createRoot } from "react-dom/client";
import { GradingOverview } from "../../src/components/grading/GradingOverview";
import type { GradingOverviewResponse } from "../../src/types";
import "../../src/styles.css";

const overview = await (await fetch("/grade-overview-fixture.json")).json() as GradingOverviewResponse;
createRoot(document.getElementById("root")!).render(
  <main style={{ maxWidth: 1000, margin: "auto", padding: 16 }}>
    <GradingOverview overview={overview} loading={false} error={null}
      onBack={() => undefined} onRefresh={async () => undefined} />
  </main>,
);
