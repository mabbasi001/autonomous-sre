"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export type Me = { email: string; display_name: string; role: string };

let meCache: Me | null = null;

export function useMe(): Me | null {
  const [me, setMe] = useState<Me | null>(meCache);
  useEffect(() => {
    if (meCache) return;
    api<Me>("/v1/me")
      .then((m) => {
        meCache = m;
        setMe(m);
      })
      .catch(() => {});
  }, []);
  return me;
}

export function usePoll<T>(fetcher: () => Promise<T>, intervalMs = 4000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetcher()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [fetcher]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, refresh };
}
