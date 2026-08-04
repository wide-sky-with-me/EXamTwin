import { websocketUrl } from "./api";

const MAX_RECONNECT_ATTEMPTS = 6;

export type TaskStreamState = "idle" | "connecting" | "live" | "reconnecting";

type TaskSnapshot<T> = {
  type: "snapshot";
  topic: string;
  resource_id: string;
  data: T;
};

type TaskStreamError = {
  type: "error";
  message: string;
};

type TaskSnapshotSubscription<T> = {
  path: string;
  onSnapshot: (snapshot: T) => void;
  isTerminal: (snapshot: T) => boolean;
  onState: (state: TaskStreamState) => void;
  onUnavailable: (message: string) => void;
  onError: (message: string) => void;
};

export function subscribeTaskSnapshots<T>(
  options: TaskSnapshotSubscription<T>,
): () => void {
  let socket: WebSocket | null = null;
  let reconnectTimer: number | undefined;
  let reconnectAttempts = 0;
  let stopped = false;

  const stop = () => {
    stopped = true;
    if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
    const current = socket;
    socket = null;
    if (current) {
      current.onopen = null;
      current.onmessage = null;
      current.onclose = null;
      current.onerror = null;
      if (current.readyState < WebSocket.CLOSING) {
        current.close(1000, "subscription complete");
      }
    }
  };

  const connect = () => {
    if (stopped) return;
    options.onState(reconnectAttempts ? "reconnecting" : "connecting");
    const current = new WebSocket(websocketUrl(options.path));
    socket = current;

    current.onopen = () => {
      options.onState("live");
    };

    current.onmessage = (event) => {
      let message: TaskSnapshot<T> | TaskStreamError;
      try {
        message = JSON.parse(event.data) as TaskSnapshot<T> | TaskStreamError;
      } catch {
        options.onError("实时任务消息无法解析，正在重新连接。");
        current.close(1003, "invalid task event");
        return;
      }
      if (message.type === "error") {
        options.onError(message.message);
        return;
      }
      if (message.type !== "snapshot" || !("data" in message)) {
        options.onError("实时任务消息格式无效，正在重新连接。");
        current.close(1003, "invalid task event");
        return;
      }
      reconnectAttempts = 0;
      options.onSnapshot(message.data);
      if (options.isTerminal(message.data)) {
        options.onState("idle");
        stop();
      }
    };

    current.onclose = (event) => {
      if (socket === current) socket = null;
      if (stopped) return;
      if (event.code === 4404) {
        stopped = true;
        options.onState("idle");
        options.onUnavailable(event.reason || "任务不存在或已被清理。");
        return;
      }
      if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS - 1) {
        stopped = true;
        options.onState("idle");
        options.onError("实时进度连接多次失败。任务仍在后台运行，可手动重新连接。");
        return;
      }
      const delay = Math.min(500 * 2 ** reconnectAttempts, 8000);
      reconnectAttempts += 1;
      options.onState("reconnecting");
      reconnectTimer = window.setTimeout(connect, delay);
    };

    current.onerror = () => {
      // The close event owns retry behavior and avoids duplicate reconnect timers.
    };
  };

  connect();
  return stop;
}
