import { CheckCircle2, CircleAlert, Info, TriangleAlert, X } from "lucide-react";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ToastContext, type ToastTone } from "./toast-context";

type Toast = { id: number; message: string; tone: ToastTone };

const toastIcons = {
  success: CheckCircle2,
  warning: TriangleAlert,
  error: CircleAlert,
  info: Info,
} as const;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
    const timer = timers.current.get(id);
    if (timer != null) window.clearTimeout(timer);
    timers.current.delete(id);
  }, []);

  const notify = useCallback((message: string, tone: ToastTone = "success") => {
    const id = nextId.current++;
    setToasts((current) => [...current, { id, message, tone }]);
    timers.current.set(id, window.setTimeout(() => dismiss(id), 5000));
  }, [dismiss]);

  useEffect(() => {
    const activeTimers = timers.current;
    return () => {
      for (const timer of activeTimers.values()) window.clearTimeout(timer);
    };
  }, []);

  const value = useMemo(() => ({ notify }), [notify]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-atomic="true" aria-live="polite" className="toast-region">
        {toasts.map((toast) => {
          const Icon = toastIcons[toast.tone];
          return (
            <div className={`toast toast-${toast.tone}`} key={toast.id} role={toast.tone === "error" ? "alert" : "status"}>
              <Icon size={18} />
              <span>{toast.message}</span>
              <button aria-label="关闭通知" onClick={() => dismiss(toast.id)} type="button">
                <X size={16} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
