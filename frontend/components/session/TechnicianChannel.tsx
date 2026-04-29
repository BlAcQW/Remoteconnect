"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type Status = "connecting" | "open" | "closed" | "reconnecting";

type Listener = (msg: Record<string, unknown>) => void;

type Channel = {
  status: Status;
  send: (payload: Record<string, unknown>) => boolean;
  subscribe: (l: Listener) => () => void;
};

const Ctx = createContext<Channel | null>(null);

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

export function useTechnicianChannel(): Channel {
  const c = useContext(Ctx);
  if (!c) throw new Error("useTechnicianChannel must be used within TechnicianChannelProvider");
  return c;
}

export function TechnicianChannelProvider({
  sessionId,
  enabled,
  children,
}: {
  sessionId: string;
  enabled: boolean;
  children: React.ReactNode;
}) {
  const wsRef = useRef<WebSocket | null>(null);
  const listenersRef = useRef<Set<Listener>>(new Set());
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const aliveRef = useRef(true);
  const [status, setStatus] = useState<Status>("connecting");

  const cleanupTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const open = useCallback(() => {
    if (!aliveRef.current) return;
    cleanupTimer();
    setStatus(attemptRef.current === 0 ? "connecting" : "reconnecting");

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/technician/${sessionId}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      attemptRef.current = 0;
      setStatus("open");
    };
    ws.onmessage = (ev) => {
      let parsed: Record<string, unknown> | null = null;
      try {
        parsed = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!parsed) return;
      for (const l of listenersRef.current) {
        try {
          l(parsed);
        } catch (err) {
          console.warn("technician channel listener threw", err);
        }
      }
    };
    ws.onerror = () => {
      // onclose will follow; let the reconnect path handle it.
    };
    ws.onclose = (ev) => {
      wsRef.current = null;
      if (!aliveRef.current) return;
      // 1008 = policy violation (auth/ownership/ended) → don't loop, surface as closed.
      if (ev.code === 1008) {
        setStatus("closed");
        return;
      }
      const wait = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** attemptRef.current);
      attemptRef.current = Math.min(attemptRef.current + 1, 10);
      setStatus("reconnecting");
      reconnectTimerRef.current = setTimeout(open, wait);
    };
  }, [cleanupTimer, sessionId]);

  useEffect(() => {
    aliveRef.current = true;
    if (!enabled) {
      setStatus("closed");
      return;
    }
    attemptRef.current = 0;
    open();
    return () => {
      aliveRef.current = false;
      cleanupTimer();
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.close();
        } catch {
          /* noop */
        }
      }
    };
  }, [enabled, open, cleanupTimer]);

  const send = useCallback((payload: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(payload));
    return true;
  }, []);

  const subscribe = useCallback((l: Listener) => {
    listenersRef.current.add(l);
    return () => {
      listenersRef.current.delete(l);
    };
  }, []);

  const value = useMemo<Channel>(() => ({ status, send, subscribe }), [status, send, subscribe]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
