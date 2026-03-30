import { NextResponse } from 'next/server';
import { supabase } from '@/lib/supabase';

interface ServiceCheck {
  service: string;
  status: 'healthy' | 'degraded' | 'down';
  response_time_ms: number;
  error_message: string | null;
}

async function checkService(name: string, url: string): Promise<ServiceCheck> {
  const start = Date.now();
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    const res = await fetch(url, { signal: controller.signal, method: 'HEAD' });
    clearTimeout(timeout);
    const elapsed = Date.now() - start;
    return {
      service: name,
      status: res.ok ? (elapsed > 3000 ? 'degraded' : 'healthy') : 'down',
      response_time_ms: elapsed,
      error_message: res.ok ? null : `HTTP ${res.status}`,
    };
  } catch (err) {
    return {
      service: name,
      status: 'down',
      response_time_ms: Date.now() - start,
      error_message: (err as Error).message,
    };
  }
}

export async function GET() {
  const checks = await Promise.all([
    (async () => {
      const start = Date.now();
      const { error } = await supabase.from('health_checks').select('id', { count: 'exact', head: true });
      return {
        service: 'supabase',
        status: error ? 'down' : 'healthy',
        response_time_ms: Date.now() - start,
        error_message: error?.message || null,
      } as ServiceCheck;
    })(),
    checkService('openrouter', 'https://openrouter.ai/api/v1/models'),
    checkService('telegram', 'https://api.telegram.org'),
    checkService('x-twitter', 'https://x.com'),
    checkService('threads', 'https://www.threads.net'),
  ]);

  // Store results in Supabase
  await supabase.from('health_checks').insert(
    checks.map((c) => ({
      service: c.service,
      status: c.status,
      response_time_ms: c.response_time_ms,
      error_message: c.error_message,
    }))
  );

  return NextResponse.json({ checks, timestamp: new Date().toISOString() });
}
