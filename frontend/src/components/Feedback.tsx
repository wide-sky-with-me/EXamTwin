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
export function Confidence({ value }: { value: number }) {
  const tone = value >= 0.8 ? "good" : value >= 0.6 ? "warn" : "bad";
  return (
    <span
      className={`confidence ${tone}`}
      title="模型置信度；不等同于官方答案、Mark scheme 或教师复核结论"
      aria-label={`模型置信度 ${Math.round(value * 100)}%`}
    >
      <span style={{ width: `${Math.round(value * 100)}%` }} />
      {Math.round(value * 100)}%
    </span>
  );
}
