import { createContext, useContext } from "react";

export type ToastTone = "success" | "warning" | "error" | "info";

type ToastContextValue = { notify: (message: string, tone?: ToastTone) => void };

export const ToastContext = createContext<ToastContextValue>({
  notify: () => undefined,
});

export function useToast() {
  return useContext(ToastContext);
}
