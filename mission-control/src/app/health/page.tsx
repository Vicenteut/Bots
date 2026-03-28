'use client';

import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { useAutoRefresh } from '@/hooks/useSupabaseRealtime';
import { format, formatDistanceToNow } from 'date-fns';
import type { HealthCheck } from '@/lib/types';
import { STATUS_COLORS } from '@/lib/types';
import { RefreshCw, Wifi, WifiOff } from 'lucide-react';

const SERVICES = ['supabase', 'openrouter', 'telegram', 'x-twitter', 'threads'];

export default function HealthPage() {
  const [checks, setChecks] = useState<HealthCheck[]>([]);
  const [pinging, setPinging] = useState(false);

  const fetchChecks = useCallback(async () => {
    const { data } = await supabase
      .from('health_checks')
      .select('*')
      .order('checked_at', { ascending: false })
      .limit(500);
    if (data) setChecks(data);
  }, []);

  useEffect(() => { fetchChecks(); }, [fetchChecks]);
  useAutoRefresh(fetchChecks, 60_000);

  const runHealthCheck = async () => {
    setPinging(true);
    try {
      await fetch('/api/health');
      await fetchChecks();
    } catch {
      // ignore
    } finally {
      setPinging(false);
    }
  };

  const getLatestForService = (service: string) => {
    return checks.find((c) => c.service === service);
  };

  const getHistoryForService = (service: string) => {
    return checks.filter((c) => c.service === service).slice(0, 24);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-semibold text-neutral-200">Health Monitor</h1>
        <button
          onClick={runHealthCheck}
          disabled={pinging}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-neutral-800 hover:bg-neutral-700 text-neutral-300 text-sm rounded-md transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={pinging ? 'animate-spin' : ''} />
          {pinging ? 'Checking...' : 'Run Check'}
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {SERVICES.map((service) => {
          const latest = getLatestForService(service);
          const history = getHistoryForService(service);

          return (
            <div key={service} className="bg-[#141414] border border-neutral-800 rounded-lg p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  {latest?.status === 'healthy' ? (
                    <Wifi size={14} className="text-green-400" />
                  ) : (
                    <WifiOff size={14} className="text-red-400" />
                  )}
                  <h3 className="text-sm font-medium text-neutral-200 capitalize">{service}</h3>
                </div>
                {latest && (
                  <span className={`w-2.5 h-2.5 rounded-full ${STATUS_COLORS[latest.status]}`} />
                )}
              </div>

              {latest ? (
                <>
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-neutral-500">Status</span>
                    <span className={`capitalize ${
                      latest.status === 'healthy' ? 'text-green-400' :
                      latest.status === 'degraded' ? 'text-yellow-400' : 'text-red-400'
                    }`}>
                      {latest.status}
                    </span>
                  </div>
                  {latest.response_time_ms !== null && (
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="text-neutral-500">Response time</span>
                      <span className="text-neutral-300 font-mono">{latest.response_time_ms}ms</span>
                    </div>
                  )}
                  <div className="flex items-center justify-between text-xs mb-3">
                    <span className="text-neutral-500">Last check</span>
                    <span className="text-neutral-500">
                      {formatDistanceToNow(new Date(latest.checked_at), { addSuffix: true })}
                    </span>
                  </div>
                  {latest.error_message && (
                    <p className="text-[10px] text-red-400 bg-red-500/10 rounded px-2 py-1 mb-3 line-clamp-2">
                      {latest.error_message}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-xs text-neutral-600 mb-3">No data yet</p>
              )}

              {/* Timeline */}
              <div className="flex items-center gap-0.5">
                {history.map((h) => (
                  <div
                    key={h.id}
                    title={`${format(new Date(h.checked_at), 'HH:mm')} - ${h.status}${h.response_time_ms ? ` (${h.response_time_ms}ms)` : ''}`}
                    className={`w-2 h-4 rounded-sm ${STATUS_COLORS[h.status]}/60`}
                  />
                ))}
                {history.length === 0 && (
                  <span className="text-[10px] text-neutral-600">No history</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
