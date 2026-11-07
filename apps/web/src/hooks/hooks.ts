import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

export function useResource<T>(url: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(url));
  const [error, setError] = useState<Error | null>(null);
  const [version, setVersion] = useState(0);
  const previousUrl = useRef(url);
  useEffect(() => {
    if (!url) {
      setData(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    let active = true;
    if (previousUrl.current !== url) setData(null);
    previousUrl.current = url;
    setLoading(true);
    setError(null);
    api<T>(url, { signal: controller.signal })
      .then((value) => {
        if (active) setData(value);
      })
      .catch((cause) => {
        if (active)
          setError(
            cause instanceof Error && cause.name !== "AbortError"
              ? cause
              : new Error("Máy chủ phản hồi quá lâu. Vui lòng thử lại."),
          );
      })
      .finally(() => {
        clearTimeout(timeout);
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [url, version]);
  return {
    data,
    loading,
    error,
    reload: () => setVersion((value) => value + 1),
  };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const running = useRef(false);
  async function run<T>(work: () => Promise<T>): Promise<T | undefined> {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      return await work();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause
          : new Error("Thao tác chưa hoàn tất. Vui lòng thử lại."),
      );
    } finally {
      running.current = false;
      setBusy(false);
    }
  }
  return { busy, error, run, setError };
}
