import { useState } from "react";
import { createRoot } from "react-dom/client";
import { TargetScoreFields, TargetScoreReport, type StrategyRequest } from "../../src/components/TargetScoreStrategy";
import type { components } from "../../src/generated/openapi";
import "../../src/styles.css";

const plan = await (await fetch("/strategy-fixture.json")).json() as components["schemas"]["StrategyPlan"];
export function Fixture() {
  const [value, setValue] = useState<StrategyRequest | null>(null);
  return <main style={{ maxWidth: 960, padding: 16, margin: "auto" }}>
    <form><TargetScoreFields value={value} onChange={setValue} economics />
      <button type="submit">开始目标作答</button></form>
    <TargetScoreReport plan={plan} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
