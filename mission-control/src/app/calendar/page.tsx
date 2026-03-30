'use client';

import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { format, startOfMonth, endOfMonth, eachDayOfInterval, startOfWeek, endOfWeek, isSameMonth, isToday, isSameDay } from 'date-fns';
import type { ScheduledTask } from '@/lib/types';
import { ChevronLeft, ChevronRight, Clock, Pause, Play } from 'lucide-react';

export default function CalendarPage() {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [selected, setSelected] = useState<ScheduledTask | null>(null);

  const fetchTasks = useCallback(async () => {
    const { data } = await supabase
      .from('scheduled_tasks')
      .select('*')
      .order('created_at', { ascending: false });
    if (data) setTasks(data);
  }, []);

  useEffect(() => { fetchTasks(); }, [fetchTasks]);

  const monthStart = startOfMonth(currentMonth);
  const monthEnd = endOfMonth(currentMonth);
  const calendarStart = startOfWeek(monthStart, { weekStartsOn: 1 });
  const calendarEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });
  const days = eachDayOfInterval({ start: calendarStart, end: calendarEnd });

  const getTasksForDay = (day: Date) => {
    return tasks.filter((t) => {
      if (t.next_run && isSameDay(new Date(t.next_run), day)) return true;
      if (t.last_run && isSameDay(new Date(t.last_run), day)) return true;
      return false;
    });
  };

  const isQuietHour = (hour: number) => hour >= 23 || hour < 8;

  return (
    <div className="flex gap-6">
      <div className="flex-1">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-lg font-semibold text-neutral-200">{format(currentMonth, 'MMMM yyyy')}</h1>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCurrentMonth((d) => new Date(d.getFullYear(), d.getMonth() - 1))}
              className="p-1.5 rounded-md hover:bg-neutral-800 text-neutral-400 transition-colors"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              onClick={() => setCurrentMonth(new Date())}
              className="px-2 py-1 text-xs text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 rounded-md transition-colors"
            >
              Today
            </button>
            <button
              onClick={() => setCurrentMonth((d) => new Date(d.getFullYear(), d.getMonth() + 1))}
              className="p-1.5 rounded-md hover:bg-neutral-800 text-neutral-400 transition-colors"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-7 gap-px bg-neutral-800 rounded-lg overflow-hidden">
          {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => (
            <div key={d} className="bg-[#0a0a0a] px-2 py-2 text-xs text-neutral-500 text-center font-medium">
              {d}
            </div>
          ))}
          {days.map((day) => {
            const dayTasks = getTasksForDay(day);
            const inMonth = isSameMonth(day, currentMonth);
            return (
              <div
                key={day.toISOString()}
                className={`bg-[#0a0a0a] min-h-[80px] p-1.5 ${!inMonth ? 'opacity-30' : ''}`}
              >
                <span
                  className={`text-xs inline-flex items-center justify-center w-6 h-6 rounded-full ${
                    isToday(day) ? 'bg-neutral-200 text-neutral-900 font-bold' : 'text-neutral-500'
                  }`}
                >
                  {format(day, 'd')}
                </span>
                <div className="mt-1 space-y-0.5">
                  {dayTasks.slice(0, 3).map((t) => (
                    <button
                      key={t.id}
                      onClick={() => setSelected(t)}
                      className={`w-full text-left text-[10px] px-1 py-0.5 rounded truncate ${
                        t.bot === 'armandito'
                          ? 'bg-blue-500/20 text-blue-400'
                          : 'bg-orange-500/20 text-orange-400'
                      }`}
                    >
                      {t.name}
                    </button>
                  ))}
                  {dayTasks.length > 3 && (
                    <span className="text-[10px] text-neutral-600">+{dayTasks.length - 3} more</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-4 flex items-center gap-4 text-xs text-neutral-500">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-blue-500/40" /> armandito
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-orange-500/40" /> sol-bot
          </div>
          <div className="flex items-center gap-1.5 ml-auto">
            <Clock size={12} /> Quiet hours: 23:00 - 08:00
          </div>
        </div>
      </div>

      {/* Detail panel */}
      <div className="hidden lg:block w-80 flex-shrink-0">
        <h2 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-3">Scheduled Tasks</h2>
        <div className="space-y-2">
          {tasks.length === 0 && <p className="text-xs text-neutral-600">No scheduled tasks</p>}
          {tasks.map((t) => (
            <button
              key={t.id}
              onClick={() => setSelected(t)}
              className={`w-full text-left bg-[#141414] border rounded-lg p-3 transition-colors duration-150 ${
                selected?.id === t.id ? 'border-neutral-600' : 'border-neutral-800 hover:border-neutral-700'
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                {t.is_active ? <Play size={10} className="text-green-400" /> : <Pause size={10} className="text-neutral-500" />}
                <span className="text-sm text-neutral-200 font-medium truncate">{t.name}</span>
              </div>
              <div className="flex items-center gap-2 text-[10px]">
                <span className={t.bot === 'armandito' ? 'text-blue-400' : 'text-orange-400'}>{t.bot}</span>
                <span className="text-neutral-600 font-mono">{t.cron_expression}</span>
              </div>
              {t.description && <p className="text-xs text-neutral-500 mt-1 line-clamp-2">{t.description}</p>}
              {t.last_run && (
                <p className="text-[10px] text-neutral-600 mt-1">
                  Last run: {format(new Date(t.last_run), 'MMM d, HH:mm')}
                </p>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
