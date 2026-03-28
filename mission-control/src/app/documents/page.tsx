'use client';

import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { formatDistanceToNow } from 'date-fns';
import ReactMarkdown from 'react-markdown';
import type { Document, BotOnly } from '@/lib/types';
import { BOT_COLORS } from '@/lib/types';
import { Search, X, Copy, Check } from 'lucide-react';

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [search, setSearch] = useState('');
  const [filterBot, setFilterBot] = useState<BotOnly | 'all'>('all');
  const [filterCategory, setFilterCategory] = useState<string>('all');
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [copied, setCopied] = useState(false);
  const [categories, setCategories] = useState<string[]>([]);

  const fetchDocs = useCallback(async () => {
    let query = supabase.from('documents').select('*').order('created_at', { ascending: false });
    if (filterBot !== 'all') query = query.eq('bot', filterBot);
    if (filterCategory !== 'all') query = query.eq('category', filterCategory);
    if (search.trim()) query = query.or(`title.ilike.%${search.trim()}%,content.ilike.%${search.trim()}%`);
    const { data } = await query.limit(200);
    if (data) {
      setDocs(data);
      const cats = [...new Set(data.map((d) => d.category).filter(Boolean))] as string[];
      setCategories(cats);
    }
  }, [search, filterBot, filterCategory]);

  useEffect(() => {
    const timer = setTimeout(fetchDocs, 300);
    return () => clearTimeout(timer);
  }, [fetchDocs]);

  const handleCopy = async (content: string) => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex gap-6 h-[calc(100vh-6rem)]">
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center gap-3 mb-4 flex-wrap">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
            <input
              type="text"
              placeholder="Search documents..."
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
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            className="bg-[#141414] border border-neutral-800 rounded-md px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:border-neutral-600"
          >
            <option value="all">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 overflow-y-auto flex-1">
          {docs.map((doc) => (
            <button
              key={doc.id}
              onClick={() => setSelectedDoc(doc)}
              className={`text-left bg-[#141414] border rounded-lg p-4 transition-colors duration-150 ${
                selectedDoc?.id === doc.id ? 'border-neutral-600' : 'border-neutral-800 hover:border-neutral-700'
              }`}
            >
              <h3 className="text-sm font-medium text-neutral-200 mb-1 truncate">{doc.title}</h3>
              <p className="text-xs text-neutral-500 line-clamp-2 mb-2">{doc.content.slice(0, 120)}</p>
              <div className="flex items-center gap-1.5 flex-wrap">
                {doc.category && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded">{doc.category}</span>
                )}
                <span className="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-500 rounded">{doc.format}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${BOT_COLORS[doc.bot]}`}>{doc.bot}</span>
                <span className="text-[10px] text-neutral-600 ml-auto">
                  {formatDistanceToNow(new Date(doc.created_at), { addSuffix: true })}
                </span>
              </div>
            </button>
          ))}
          {docs.length === 0 && (
            <p className="text-sm text-neutral-600 col-span-full text-center py-8">No documents found</p>
          )}
        </div>
      </div>

      {/* Document viewer */}
      {selectedDoc && (
        <div className="hidden lg:flex flex-col w-[480px] flex-shrink-0 bg-[#141414] border border-neutral-800 rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800">
            <h2 className="text-sm font-medium text-neutral-200 truncate flex-1">{selectedDoc.title}</h2>
            <div className="flex items-center gap-2 ml-2">
              <button
                onClick={() => handleCopy(selectedDoc.content)}
                className="p-1.5 rounded-md hover:bg-neutral-800 text-neutral-500 transition-colors"
              >
                {copied ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
              </button>
              <button
                onClick={() => setSelectedDoc(null)}
                className="p-1.5 rounded-md hover:bg-neutral-800 text-neutral-500 transition-colors"
              >
                <X size={14} />
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-4 prose prose-sm prose-invert max-w-none">
            <ReactMarkdown>{selectedDoc.content}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
