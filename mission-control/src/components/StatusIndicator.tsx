'use client';

import { useEffect, useState } from 'react';
import { checkConnection } from '@/lib/supabase';

export default function StatusIndicator() {
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    const check = async () => setConnected(await checkConnection());
    check();
    const interval = setInterval(check, 30_000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex items-center gap-2 text-xs text-neutral-500">
      <span
        className={`w-2 h-2 rounded-full ${
          connected === null ? 'bg-neutral-600' : connected ? 'bg-green-500' : 'bg-red-500'
        }`}
      />
      {connected === null ? 'Checking...' : connected ? 'Connected' : 'Disconnected'}
    </div>
  );
}
