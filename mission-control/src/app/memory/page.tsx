'use client';

import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { format, isSameDay } from 'date-fns';
import type { Memory, MemoryType, BotOnly } from '@/lib/types';
import { BOT_COLORS } from '@/lib/types';
import { Search, ChevronDown, ChevronRight } from 'lucide-react';

const MAX_DAILY_LINES = 200;
const MAX_LONGTERM_LINES = 300;

export default function MemoryPage() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [search, setSearch] = useState('');
  const [filterBot, setFilterBot] = useState<BotOnly | 'all'>('all');
  const [filterType, setFilterType] = useState<MemoryType | 'all'>('all');
  const [showLongTerm, setShowLongTerm] = useState(false);

  const fetchMemories = useCallback(async () => {
    let query = supabase.from('memories').select('*').order('created_at', { ascending: false });
    if (filterBot !== 'all') query = query.eq('bot', filterBot);
    if (filterType !== 'all') query = query.eq('memory_type', filterType);
    if (search.trim()) query = query.ilike('content', `%${search.trim()}%`);
    const { data } = await query.limit(500);
    if (data) setMemories(data);
  }, [search, filterBot, filterType]);

  useEffect(() => {
    const timer = setTimeout(fetchMemories, 300);
    return () => clearTimeout(timer);
  }, [fetchMemories]);

  const conversationMemories = memories.filter((m) => m.memory_type !== 'long_term');
  const longTermMemories = memories.filter((m) => m.memory_type === 'long_term');

  const groupedByDay: Record<string, Memory[]> = {};
  conversationMemories.forEach((m) => {
    const key = format(new Date(m.created_at), 'yyyy-MM-dd');
    if (!groupedByDay[key]) groupedByDay[key] = [];
    groupedByDay[key].push(m);
  });

  const getDayLineCount = (mems: Memory[]) => mems.reduce((acc, m) => acc + m.content.split('\n').length, 0);
  const longTermLineCount = longTermMemories.reduce((acc, m) => acc + m.content.split('\n').length, 0);

  return (
    <div>
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
          <input
            type="text"
            placeholder="Search memories..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-[#141414] border border-neutral-800 rounded-md pl-9 pr-3 py-2 text-sm text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-neutral-600"
          />
        </div>
        <select
          value={filterBot}
          onChange={(e) => setFilterBot(e.target.value as BotOnly | 'all')}
          className="bg-[#141414] border border-neutral-800 rounded-md px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:border-neutral-600"
        >
          <option value="all">All bots</option>
          <option value="armandito">Armandito</option>
          <option value="sol-bot">Sol-bot</option>
        </select>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as MemoryType | 'all')}
          className="bg-[#141414] border border-neutral-800 rounded-md px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:border-neutral-600"
        >
          <option value="all">All types</option>
          <option value="conversation">Conversation</option>
          <option value="long_term">Long-term</option>
          <option value="context">Context</option>
        </select>
      </div>

      {/* Long-term memories section */}
      <button
        onClick={() => setShowLongTerm(!showLongTerm)}
        className="flex items-center gap-2 mb-4 text-sm text-neutral-400 hover:text-neutral-200 transition-colors"
      >
        {showLongTerm ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        Long-term Memories
        <span className={`text-xs px-1.5 py-0.5 rounded ${longTermLineCount > MAX_LONGTERM_LINES ? 'bg-red-500/20 text-red-400' : 'bg-neutral-800 text-neutral-500'}`}>
          {longTermLineCount}/{MAX_LONGTERM_LINES} lines
        </span>
      </button>
      {showLongTerm && (
        <div className="mb-6 space-y-2">
          {longTermMemories.length === 0 && <p className="text-xs text-neutral-600">No long-term memories</p>}
          {longTermMemories.map((m) => (
            <MemoryCard key={m.id} memory={m} />
          ))}
        </div>
      )}

      {/* Daily memories */}
      <div className="space-y-6">
        {Object.entries(groupedByDay).map(([date, mems]) => {
          const lineCount = getDayLineCount(mems);
          return (
            <div key={date}>
              <div className="flex items-center gap-2 mb-2">
                <h2 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider">
                  {format(new Date(date), 'EEEE, MMMM d, yyyy')}
                </h2>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${lineCount > MAX_DAILY_LINES ? 'bg-red-500/20 text-red-400' : 'bg-neutral-800 text-neutral-500'}`}>
                  {lineCount}/{MAX_DAILY_LINES} lines
                </span>
              </div>
              <div className="space-y-2">
                {mems.map((m) => (
                  <MemoryCard key={m.id} memory={m} />
                ))}
              </div>
            </div>
          );
        })}
        {Object.keys(groupedByDay).length === 0 && conversationMemories.length === 0 && (
          <p className="text-sm text-neutral-600 text-center py-8">No memories found</p>
        )}
      </div>
    </div>
  );
}

function MemoryCard({ memory }: { memory: Memory }) {
  return (
    <div className="bg-[#141414] border border-neutral-800 rounded-lg p-3">
      <div className="flex items-center gap-2 mb-2">
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${BOT_COLORS[memory.bot]}`}>
          {memory.bot}
        </span>
        <span className="text-[10px] text-neutral-600 bg-neutral-800 px-1.5 py-0.5 rounded">
          {memory.memory_type}
        </span>
        <span className="text-[10px] text-neutral-600 ml-auto">
          {format(new Date(memory.created_at), 'HH:mm')}
        </span>
      </div>
      <p className="text-sm text-neutral-300 whitespace-pre-wrap">{memory.content}</p>
      {memory.tags && memory.tags.length > 0 && (
        <div className="flex gap-1 mt-2 flex-wrap">
          {memory.tags.map((tag) => (
            <span key={tag} className="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-500 rounded">
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
