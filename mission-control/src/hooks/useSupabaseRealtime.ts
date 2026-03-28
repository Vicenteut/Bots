'use client';

import { useEffect, useCallback, useRef, useState } from 'react';
import { supabase } from '@/lib/supabase';

export function useSupabaseRealtime(table: string, onUpdate: () => void) {
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  useEffect(() => {
    const channel = supabase
      .channel(`realtime-${table}`)
      .on('postgres_changes', { event: '*', schema: 'public', table }, () => {
        onUpdateRef.current();
      })
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [table]);
}

export function useAutoRefresh(callback: () => void, intervalMs: number = 30_000) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    const interval = setInterval(() => callbackRef.current(), intervalMs);
    return () => clearInterval(interval);
  }, [intervalMs]);
}

export function useFetchData<T>(fetcher: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await fetcher();
      setData(result);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
}
