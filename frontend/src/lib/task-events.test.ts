import { afterEach, describe, expect, test, vi } from "vitest";
import { subscribeTaskSnapshots } from "./task-events";

type CloseHandler = ((event: CloseEvent) => void) | null;

class FailingSocket {
  static CLOSING = 2;
  static instances: FailingSocket[] = [];

  readyState = 0;
  onclose: CloseHandler = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;

  constructor() {
    FailingSocket.instances.push(this);
  }

  close() {}
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  FailingSocket.instances = [];
});

describe("task event subscription", () => {
  test("stops reconnecting after a bounded outage and exposes manual recovery", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FailingSocket);
    const onError = vi.fn();
    const onState = vi.fn();

    subscribeTaskSnapshots({
      path: "/papers/jobs/job-1/events",
      onSnapshot: vi.fn(),
      isTerminal: () => false,
      onState,
      onUnavailable: vi.fn(),
      onError,
    });

    for (let attempt = 0; attempt < 6; attempt += 1) {
      FailingSocket.instances[attempt].onclose?.({ code: 1006, reason: "" } as CloseEvent);
      vi.runOnlyPendingTimers();
    }

    expect(FailingSocket.instances).toHaveLength(6);
    expect(onState).toHaveBeenLastCalledWith("idle");
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("手动重新连接"));
  });
});
