'use client';

import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { format, subDays, startOfDay, startOfWeek, startOfMonth } from 'date-fns';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import type { ApiUsage } from '@/lib/types';
import { useAutoRefresh } from '@/hooks/useSupabaseRealtime';
import { AlertTriangle, TrendingUp, DollarSign } from 'lucide-react';

const COST_THRESHOLD = 50;
const PIE_COLORS = ['#3b82f6', '#f97316'];

export default function CostsPage() {
  const [usage, setUsage] = useState<ApiUsage[]>([]);
  const [allUsage, setAllUsage] = useState<ApiUsage[]>([]);

  const fetchUsage = useCallback(async () => {
    const thirtyDaysAgo = subDays(new Date(), 30).toISOString();
    const { data } = await supabase
      .from('api_usage')
      .select('*')
      .gte('created_at', thirtyDaysAgo)
      .order('created_at', { ascending: false });
    if (data) {
      setUsage(data.slice(0, 100));
      setAllUsage(data);
    }
  }, []);

  useEffect(() => { fetchUsage(); }, [fetchUsage]);
  useAutoRefresh(fetchUsage, 30_000);

  const today = startOfDay(new Date());
  const weekStart = startOfWeek(new Date(), { weekStartsOn: 1 });
  const monthStart = startOfMonth(new Date());

  const costToday = allUsage.filter((u) => new Date(u.created_at) >= today).reduce((s, u) => s + Number(u.cost_usd), 0);
  const costWeek = allUsage.filter((u) => new Date(u.created_at) >= weekStart).reduce((s, u) => s + Number(u.cost_usd), 0);
  const costMonth = allUsage.filter((u) => new Date(u.created_at) >= monthStart).reduce((s, u) => s + Number(u.cost_usd), 0);

  const daysInMonth = new Date().getDate();
  const projection = daysInMonth > 0 ? (costMonth / daysInMonth) * 30 : 0;

  // Daily cost chart data
  const dailyCosts: Record<string, { date: string; armandito: number; 'sol-bot': number }> = {};
  for (let i = 29; i >= 0; i--) {
    const d = format(subDays(new Date(), i), 'MMM d');
    dailyCosts[d] = { date: d, armandito: 0, 'sol-bot': 0 };
  }
  allUsage.forEach((u) => {
    const d = format(new Date(u.created_at), 'MMM d');
    if (dailyCosts[d]) dailyCosts[d][u.bot as 'armandito' | 'sol-bot'] += Number(u.cost_usd);
  });
  const dailyData = Object.values(dailyCosts);

  // Model usage chart
  const modelCosts: Record<string, number> = {};
  allUsage.forEach((u) => { modelCosts[u.model] = (modelCosts[u.model] || 0) + Number(u.cost_usd); });
  const modelData = Object.entries(modelCosts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([model, cost]) => ({ model: model.split('/').pop() || model, cost: +cost.toFixed(4) }));

  // Bot distribution
  const botCosts = [
    { name: 'armandito', value: +allUsage.filter((u) => u.bot === 'armandito').reduce((s, u) => s + Number(u.cost_usd), 0).toFixed(4) },
    { name: 'sol-bot', value: +allUsage.filter((u) => u.bot === 'sol-bot').reduce((s, u) => s + Number(u.cost_usd), 0).toFixed(4) },
  ];

  return (
    <div>
      {costMonth > COST_THRESHOLD && (
        <div className="flex items-center gap-2 mb-4 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-lg">
          <AlertTriangle size={16} className="text-red-400" />
          <span className="text-sm text-red-400">Monthly spending (${costMonth.toFixed(2)}) exceeds ${COST_THRESHOLD} threshold</span>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        {[
          { label: 'Today', value: costToday, icon: DollarSign },
          { label: 'This Week', value: costWeek, icon: DollarSign },
          { label: 'This Month', value: costMonth, icon: DollarSign },
          { label: 'Projection', value: projection, icon: TrendingUp },
        ].map((kpi) => (
          <div key={kpi.label} className="bg-[#141414] border border-neutral-800 rounded-lg p-4">
            <div className="flex items-center gap-1.5 text-xs text-neutral-500 mb-1">
              <kpi.icon size={12} />
              {kpi.label}
            </div>
            <p className="text-lg font-semibold text-neutral-200">${kpi.value.toFixed(4)}</p>
          </div>
        ))}
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className="lg:col-span-2 bg-[#141414] border border-neutral-800 rounded-lg p-4">
          <h3 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-3">Daily Cost (30 days)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={dailyData}>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#525252' }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 10, fill: '#525252' }} width={40} />
              <Tooltip contentStyle={{ background: '#141414', border: '1px solid #262626', borderRadius: 6, fontSize: 12 }} />
              <Line type="monotone" dataKey="armandito" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey="sol-bot" stroke="#f97316" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-[#141414] border border-neutral-800 rounded-lg p-4">
          <h3 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-3">By Bot</h3>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie data={botCosts} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} strokeWidth={0}>
                {botCosts.map((_, i) => (
                  <Cell key={i} fill={PIE_COLORS[i]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: '#141414', border: '1px solid #262626', borderRadius: 6, fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="flex justify-center gap-4 mt-2">
            {botCosts.map((b, i) => (
              <div key={b.name} className="flex items-center gap-1.5 text-xs text-neutral-400">
                <span className="w-2 h-2 rounded-full" style={{ background: PIE_COLORS[i] }} />
                {b.name}: ${b.value}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Model bar chart */}
      <div className="bg-[#141414] border border-neutral-800 rounded-lg p-4 mb-6">
        <h3 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-3">Top Models by Cost</h3>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={modelData} layout="vertical">
            <XAxis type="number" tick={{ fontSize: 10, fill: '#525252' }} />
            <YAxis type="category" dataKey="model" tick={{ fontSize: 10, fill: '#525252' }} width={120} />
            <Tooltip contentStyle={{ background: '#141414', border: '1px solid #262626', borderRadius: 6, fontSize: 12 }} />
            <Bar dataKey="cost" fill="#525252" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Usage table */}
      <div className="bg-[#141414] border border-neutral-800 rounded-lg overflow-hidden">
        <h3 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider px-4 py-3 border-b border-neutral-800">
          Recent API Calls
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-neutral-800 text-neutral-500">
                <th className="text-left px-4 py-2 font-medium">Time</th>
                <th className="text-left px-4 py-2 font-medium">Bot</th>
                <th className="text-left px-4 py-2 font-medium">Model</th>
                <th className="text-right px-4 py-2 font-medium">In</th>
                <th className="text-right px-4 py-2 font-medium">Out</th>
                <th className="text-right px-4 py-2 font-medium">Cost</th>
                <th className="text-left px-4 py-2 font-medium">Description</th>
              </tr>
            </thead>
            <tbody>
              {usage.map((u) => (
                <tr key={u.id} className="border-b border-neutral-800/50 hover:bg-neutral-800/30">
                  <td className="px-4 py-2 text-neutral-500 whitespace-nowrap">{format(new Date(u.created_at), 'MMM d HH:mm')}</td>
                  <td className="px-4 py-2"><span className={`px-1.5 py-0.5 rounded text-[10px] ${u.bot === 'armandito' ? 'bg-blue-500/20 text-blue-400' : 'bg-orange-500/20 text-orange-400'}`}>{u.bot}</span></td>
                  <td className="px-4 py-2 text-neutral-400 font-mono">{(u.model.split('/').pop() || u.model).slice(0, 20)}</td>
                  <td className="px-4 py-2 text-neutral-500 text-right">{u.tokens_input.toLocaleString()}</td>
                  <td className="px-4 py-2 text-neutral-500 text-right">{u.tokens_output.toLocaleString()}</td>
                  <td className="px-4 py-2 text-neutral-300 text-right font-mono">${Number(u.cost_usd).toFixed(4)}</td>
                  <td className="px-4 py-2 text-neutral-500 truncate max-w-[200px]">{u.task_description || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {usage.length === 0 && (
            <p className="text-sm text-neutral-600 text-center py-8">No API usage recorded</p>
          )}
        </div>
      </div>
    </div>
  );
}
