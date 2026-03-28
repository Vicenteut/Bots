'use client';

import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { useSupabaseRealtime } from '@/hooks/useSupabaseRealtime';
import { formatDistanceToNow } from 'date-fns';
import type { ActivityLog } from '@/lib/types';
import { BOT_COLORS } from '@/lib/types';

export default function ActivityFeed() {
  const [logs, setLogs] = useState<ActivityLog[]>([]);

  const fetchLogs = useCallback(async () => {
    const { data } = await supabase
      .from('activity_log')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(50);
    if (data) setLogs(data);
  }, []);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);
  useSupabaseRealtime('activity_log', fetchLogs);

  return (
    <div className="bg-[#141414] border border-neutral-800 rounded-lg p-4 h-full">
      <h3 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-3">Activity Feed</h3>
      <div className="space-y-2 overflow-y-auto max-h-[calc(100vh-16rem)]">
        {logs.length === 0 && (
          <p className="text-xs text-neutral-600">No activity yet</p>
        )}
        {logs.map((log) => (
          <div key={log.id} className="flex items-start gap-2 text-xs">
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${BOT_COLORS[log.bot]}`}>
              {log.bot}
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-neutral-300 truncate">{log.action}</p>
              <p className="text-neutral-600">
                {formatDistanceToNow(new Date(log.created_at), { addSuffix: true })}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
