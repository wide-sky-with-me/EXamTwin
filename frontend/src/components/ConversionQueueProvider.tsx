import { type ReactNode, useEffect, useState } from "react";

import { ConversionQueueContext, createConversionQueue } from "../lib/conversion-queue";
import { useToast } from "./toast-context";

export function ConversionQueueProvider({ children }: { children: ReactNode }) {
  const [queue] = useState(createConversionQueue);
  const { notify } = useToast();

  useEffect(() => queue.onEvent(({ tone, message }) => notify(message, tone)), [notify, queue]);

  return <ConversionQueueContext.Provider value={queue}>{children}</ConversionQueueContext.Provider>;
}
