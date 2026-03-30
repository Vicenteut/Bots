'use client';

import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { useSupabaseRealtime } from '@/hooks/useSupabaseRealtime';
import { formatDistanceToNow } from 'date-fns';
import ActivityFeed from '@/components/ActivityFeed';
import type { Task, TaskStatus, Priority, BotName } from '@/lib/types';
import { PRIORITY_COLORS, BOT_COLORS } from '@/lib/types';
import { Plus, X } from 'lucide-react';

const COLUMNS: { status: TaskStatus; label: string }[] = [
  { status: 'backlog', label: 'Backlog' },
  { status: 'in_progress', label: 'In Progress' },
  { status: 'review', label: 'Review' },
  { status: 'done', label: 'Done' },
];

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [draggedTask, setDraggedTask] = useState<string | null>(null);

  const fetchTasks = useCallback(async () => {
    const { data } = await supabase
      .from('tasks')
      .select('*')
      .order('created_at', { ascending: false });
    if (data) setTasks(data);
  }, []);

  useEffect(() => { fetchTasks(); }, [fetchTasks]);
  useSupabaseRealtime('tasks', fetchTasks);

  const moveTask = async (taskId: string, newStatus: TaskStatus) => {
    setTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, status: newStatus } : t))
    );
    await supabase.from('tasks').update({ status: newStatus, updated_at: new Date().toISOString() }).eq('id', taskId);
  };

  const handleDrop = (status: TaskStatus) => {
    if (draggedTask) {
      moveTask(draggedTask, status);
      setDraggedTask(null);
    }
  };

  return (
    <div className="flex gap-6 h-[calc(100vh-6rem)]">
      <div className="flex-1 flex gap-3 overflow-x-auto">
        {COLUMNS.map((col) => {
          const columnTasks = tasks.filter((t) => t.status === col.status);
          return (
            <div
              key={col.status}
              className="flex-1 min-w-[240px] flex flex-col"
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => handleDrop(col.status)}
            >
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider">
                  {col.label}
                </h2>
                <span className="text-xs text-neutral-600">{columnTasks.length}</span>
              </div>
              <div className="flex-1 space-y-2 overflow-y-auto">
                {columnTasks.map((task) => (
                  <div
                    key={task.id}
                    draggable
                    onDragStart={() => setDraggedTask(task.id)}
                    className="bg-[#141414] border border-neutral-800 rounded-lg p-3 cursor-grab active:cursor-grabbing hover:border-neutral-700 transition-colors duration-150"
                  >
                    <h3 className="text-sm text-neutral-200 font-medium mb-1">{task.title}</h3>
                    {task.description && (
                      <p className="text-xs text-neutral-500 mb-2 line-clamp-2">{task.description}</p>
                    )}
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${PRIORITY_COLORS[task.priority]}`}>
                        {task.priority}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${BOT_COLORS[task.assigned_to]}`}>
                        {task.assigned_to}
                      </span>
                      <span className="text-[10px] text-neutral-600 ml-auto">
                        {formatDistanceToNow(new Date(task.created_at), { addSuffix: true })}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="hidden lg:block w-72 flex-shrink-0">
        <div className="mb-3">
          <button
            onClick={() => setShowModal(true)}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-2 bg-neutral-800 hover:bg-neutral-700 text-neutral-300 text-sm rounded-md transition-colors duration-150"
          >
            <Plus size={14} /> New Task
          </button>
        </div>
        <ActivityFeed />
      </div>

      {showModal && <NewTaskModal onClose={() => setShowModal(false)} onCreated={fetchTasks} />}
    </div>
  );
}

function NewTaskModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<Priority>('medium');
  const [assignedTo, setAssignedTo] = useState<BotName>('user');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setSubmitting(true);
    await supabase.from('tasks').insert({
      title: title.trim(),
      description: description.trim() || null,
      priority,
      assigned_to: assignedTo,
    });
    onCreated();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[#141414] border border-neutral-800 rounded-lg p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-neutral-200">New Task</h2>
          <button onClick={onClose} className="text-neutral-500 hover:text-neutral-300"><X size={16} /></button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="text"
            placeholder="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full bg-[#0a0a0a] border border-neutral-800 rounded-md px-3 py-2 text-sm text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-neutral-600"
            autoFocus
          />
          <textarea
            placeholder="Description (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full bg-[#0a0a0a] border border-neutral-800 rounded-md px-3 py-2 text-sm text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-neutral-600 resize-none"
          />
          <div className="flex gap-3">
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
              className="flex-1 bg-[#0a0a0a] border border-neutral-800 rounded-md px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:border-neutral-600"
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
            <select
              value={assignedTo}
              onChange={(e) => setAssignedTo(e.target.value as BotName)}
              className="flex-1 bg-[#0a0a0a] border border-neutral-800 rounded-md px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:border-neutral-600"
            >
              <option value="user">User</option>
              <option value="armandito">Armandito</option>
              <option value="sol-bot">Sol-bot</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={!title.trim() || submitting}
            className="w-full bg-neutral-200 text-neutral-900 rounded-md px-3 py-2 text-sm font-medium hover:bg-neutral-300 disabled:opacity-50 transition-colors duration-150"
          >
            {submitting ? 'Creating...' : 'Create Task'}
          </button>
        </form>
      </div>
    </div>
  );
}
