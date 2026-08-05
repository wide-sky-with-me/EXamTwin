import { createContext, useContext } from "react";

type ToastContextValue = { notify: (message: string) => void };

export const ToastContext = createContext<ToastContextValue>({
  notify: () => undefined,
});

export function useToast() {
  return useContext(ToastContext);
}
