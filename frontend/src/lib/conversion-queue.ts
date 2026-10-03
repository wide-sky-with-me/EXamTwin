import { createContext, useContext, useEffect, useState, useSyncExternalStore } from "react";

import type { SourceDocument } from "../types";
import { apiClient, subjectHeaders, unwrapApi } from "./api";

export type ConversionState = "queued" | "converting" | "failed";

export type ConversionSnapshot = {
  /** Local progress for documents the queue owns; absent entries follow the server status. */
  states: Readonly<Partial<Record<string, ConversionState>>>;
  activeDocumentId: string | null;
  /** Increments after every finished conversion so views can refresh document rows. */
  finished: number;
};

export type ConversionEvent = {
  tone: "success" | "error";
  message: string;
};

type QueueItem = { document: SourceDocument; subjectId: string };

function documentLabel(document: Pick<SourceDocument, "display_name" | "filename">) {
  return document.display_name || document.filename;
}

async function convertDocument({ document, subjectId }: QueueItem): Promise<boolean> {
  const conversion = await unwrapApi(
    apiClient.POST("/api/v1/corpus/convert", {
      headers: subjectHeaders(subjectId),
      body: {
        authority_tiers: [],
        document_ids: [document.id],
        force: false,
        limit: 1,
        source_types: [document.source_type],
        workers: 1,
      },
    }),
  );
  if (conversion.failed || conversion.succeeded + conversion.skipped !== 1) {
    throw new Error(conversion.errors.filter(Boolean).join("；") || "资料解析未完成，请重试。");
  }
  return conversion.skipped > 0;
}

/**
 * Serial document conversion queue. It is owned above the routed pages so a queue started
 * from the paper catalog keeps running, and keeps reporting, after the user navigates away.
 */
export function createConversionQueue() {
  let snapshot: ConversionSnapshot = { states: {}, activeDocumentId: null, finished: 0 };
  let pending: QueueItem[] = [];
  const listeners = new Set<() => void>();
  const eventListeners = new Set<(event: ConversionEvent) => void>();

  function update(next: Partial<ConversionSnapshot>) {
    snapshot = { ...snapshot, ...next };
    listeners.forEach((listener) => listener());
  }

  function setState(documentId: string, state: ConversionState | null) {
    const states = { ...snapshot.states };
    if (state) states[documentId] = state;
    else delete states[documentId];
    update({ states });
  }

  function report(event: ConversionEvent) {
    eventListeners.forEach((listener) => listener(event));
  }

  async function runNext() {
    if (snapshot.activeDocumentId || !pending.length) return;
    const item = pending[0];
    pending = pending.slice(1);
    update({ activeDocumentId: item.document.id });
    setState(item.document.id, "converting");
    try {
      const skipped = await convertDocument(item);
      setState(item.document.id, null);
      report({
        tone: "success",
        message: skipped
          ? `${documentLabel(item.document)} 已有可用解析结果。`
          : `${documentLabel(item.document)} 解析完成。`,
      });
    } catch (cause) {
      setState(item.document.id, "failed");
      report({
        tone: "error",
        message: cause instanceof Error ? cause.message : `${documentLabel(item.document)} 解析失败。`,
      });
    } finally {
      update({ activeDocumentId: null, finished: snapshot.finished + 1 });
      void runNext();
    }
  }

  return {
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    getSnapshot() {
      return snapshot;
    },
    onEvent(listener: (event: ConversionEvent) => void) {
      eventListeners.add(listener);
      return () => { eventListeners.delete(listener); };
    },
    /** Queues documents that are not converted, queued or converting; returns how many were added. */
    enqueue(documents: SourceDocument[], subjectId: string): number {
      const queuedIds = new Set(pending.map((item) => item.document.id));
      const fresh = documents.filter((document, index) => {
        const state = snapshot.states[document.id];
        return documents.findIndex((candidate) => candidate.id === document.id) === index
          && !queuedIds.has(document.id)
          && state !== "queued"
          && state !== "converting"
          && (state === "failed" || !["converted", "indexed"].includes(document.status));
      });
      if (!fresh.length) return 0;
      pending = [...pending, ...fresh.map((document) => ({ document, subjectId }))];
      update({
        states: fresh.reduce(
          (states, document) => ({ ...states, [document.id]: "queued" as const }),
          snapshot.states,
        ),
      });
      void runNext();
      return fresh.length;
    },
  };
}

export type ConversionQueue = ReturnType<typeof createConversionQueue>;

export const ConversionQueueContext = createContext<ConversionQueue | null>(null);

/**
 * The app-wide queue when one is provided, otherwise a queue owned by the calling view.
 * `notify` receives completion events only for an owned queue; the provider reports its own.
 */
export function useConversionQueue(notify: (message: string, tone: ConversionEvent["tone"]) => void) {
  const shared = useContext(ConversionQueueContext);
  const [owned] = useState(() => shared ? null : createConversionQueue());
  const queue = shared ?? owned!;
  const snapshot = useSyncExternalStore(queue.subscribe, queue.getSnapshot);
  useEffect(() => {
    if (shared) return;
    return queue.onEvent(({ tone, message }) => notify(message, tone));
  }, [notify, queue, shared]);
  return { queue, snapshot };
}
