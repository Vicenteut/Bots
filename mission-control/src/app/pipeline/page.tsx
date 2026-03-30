'use client';

import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { useSupabaseRealtime, useAutoRefresh } from '@/hooks/useSupabaseRealtime';
import { formatDistanceToNow, format } from 'date-fns';
import type { Publication, PublicationStatus, Platform, TweetType } from '@/lib/types';
import { PUBLICATION_STATUS_COLORS } from '@/lib/types';
import { ExternalLink, AlertCircle } from 'lucide-react';

const PIPELINE_STAGES: PublicationStatus[] = ['draft', 'generating', 'ready', 'publishing', 'published', 'failed'];

export default function PipelinePage() {
  const [pubs, setPubs] = useState<Publication[]>([]);
  const [filterStatus, setFilterStatus] = useState<PublicationStatus | 'all'>('all');
  const [filterPlatform, setFilterPlatform] = useState<Platform | 'all'>('all');
  const [filterType, setFilterType] = useState<TweetType | 'all'>('all');

  const fetchPubs = useCallback(async () => {
    let query = supabase.from('publications').select('*').order('created_at', { ascending: false });
    if (filterStatus !== 'all') query = query.eq('status', filterStatus);
    if (filterPlatform !== 'all') query = query.eq('platform', filterPlatform);
    if (filterType !== 'all') query = query.eq('tweet_type', filterType);
    const { data } = await query.limit(200);
    if (data) setPubs(data);
  }, [filterStatus, filterPlatform, filterType]);

  useEffect(() => { fetchPubs(); }, [fetchPubs]);
  useSupabaseRealtime('publications', fetchPubs);
  useAutoRefresh(fetchPubs, 30_000);

  const stageCounts = PIPELINE_STAGES.reduce((acc, s) => {
    acc[s] = pubs.filter((p) => p.status === s).length;
    return acc;
  }, {} as Record<string, number>);

  return (
    <div>
      {/* Pipeline visualization */}
      <div className="flex items-center gap-1 mb-6 overflow-x-auto pb-2">
        {PIPELINE_STAGES.map((stage, i) => (
          <div key={stage} className="flex items-center">
            <button
              onClick={() => setFilterStatus(filterStatus === stage ? 'all' : stage)}
              className={`flex flex-col items-center px-4 py-2 rounded-lg border transition-colors min-w-[100px] ${
                filterStatus === stage
                  ? 'border-neutral-600 bg-neutral-800'
                  : 'border-neutral-800 bg-[#141414] hover:border-neutral-700'
              }`}
            >
              <span className={`text-[10px] font-medium uppercase ${PUBLICATION_STATUS_COLORS[stage].split(' ')[1]}`}>
                {stage}
              </span>
              <span className="text-lg font-semibold text-neutral-200 mt-0.5">{stageCounts[stage] || 0}</span>
            </button>
            {i < PIPELINE_STAGES.length - 1 && (
              <span className="text-neutral-700 mx-1">→</span>
            )}
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4">
        <select
          value={filterPlatform}
          onChange={(e) => setFilterPlatform(e.target.value as Platform | 'all')}
          className="bg-[#141414] border border-neutral-800 rounded-md px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:border-neutral-600"
        >
          <option value="all">All platforms</option>
          <option value="x">X / Twitter</option>
          <option value="threads">Threads</option>
          <option value="both">Both</option>
        </select>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as TweetType | 'all')}
          className="bg-[#141414] border border-neutral-800 rounded-md px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:border-neutral-600"
        >
          <option value="all">All types</option>
          <option value="WIRE">Wire</option>
          <option value="DEBATE">Debate</option>
          <option value="ANALISIS">Analisis</option>
          <option value="CONEXION">Conexion</option>
        </select>
      </div>

      {/* Publications grid */}
      <div className="space-y-3">
        {pubs.map((pub) => (
          <div
            key={pub.id}
            className={`bg-[#141414] border rounded-lg p-4 ${
              pub.status === 'failed' ? 'border-red-500/30' : 'border-neutral-800'
            }`}
          >
            <div className="flex items-start justify-between gap-3 mb-2">
              <h3 className="text-sm font-medium text-neutral-200 flex-1">{pub.headline}</h3>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${PUBLICATION_STATUS_COLORS[pub.status]}`}>
                  {pub.status}
                </span>
                {pub.tweet_type && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded">
                    {pub.tweet_type}
                  </span>
                )}
                <span className="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-500 rounded">
                  {pub.platform}
                </span>
              </div>
            </div>
            <p className="text-xs text-neutral-500 line-clamp-2 mb-2">{pub.content}</p>

            {pub.status === 'failed' && pub.error_message && (
              <div className="flex items-start gap-1.5 text-xs text-red-400 bg-red-500/10 rounded px-2 py-1.5 mb-2">
                <AlertCircle size={12} className="flex-shrink-0 mt-0.5" />
                {pub.error_message}
              </div>
            )}

            <div className="flex items-center gap-3 text-[10px] text-neutral-600">
              <span>{formatDistanceToNow(new Date(pub.created_at), { addSuffix: true })}</span>
              {pub.published_at && <span>Published: {format(new Date(pub.published_at), 'MMM d, HH:mm')}</span>}
              {pub.x_post_url && (
                <a href={pub.x_post_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-0.5 text-blue-400 hover:text-blue-300">
                  <ExternalLink size={10} /> X
                </a>
              )}
              {pub.threads_post_url && (
                <a href={pub.threads_post_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-0.5 text-purple-400 hover:text-purple-300">
                  <ExternalLink size={10} /> Threads
                </a>
              )}
              {pub.engagement && Object.keys(pub.engagement).length > 0 && (
                <span className="ml-auto text-neutral-500">
                  {Object.entries(pub.engagement).map(([k, v]) => `${k}: ${v}`).join(' | ')}
                </span>
              )}
            </div>
          </div>
        ))}
        {pubs.length === 0 && (
          <p className="text-sm text-neutral-600 text-center py-8">No publications found</p>
        )}
      </div>
    </div>
  );
}
