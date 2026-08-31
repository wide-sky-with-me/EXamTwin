import { TriangleAlert } from "lucide-react";

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="error-banner" role="alert">
      <TriangleAlert size={18} />
      <span>{message}</span>
    </div>
  );
}
export function Confidence({
  value,
  accessibleLabel = "模型置信度",
  helpText = "模型置信度；不等同于官方答案、Mark scheme 或教师复核结论",
}: {
  value: number;
  accessibleLabel?: string;
  helpText?: string;
}) {
  const tone = value >= 0.8 ? "good" : value >= 0.6 ? "warn" : "bad";
  return (
    <span
      aria-label={`${accessibleLabel} ${Math.round(value * 100)}%`}
      className={`confidence ${tone}`}
      title={helpText}
    >
      <span style={{ width: `${Math.round(value * 100)}%` }} />
      {Math.round(value * 100)}%
    </span>
  );
}
