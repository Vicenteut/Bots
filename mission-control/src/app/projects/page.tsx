'use client';

import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { formatDistanceToNow } from 'date-fns';
import type { Project, Task } from '@/lib/types';
import { FolderKanban, ChevronRight } from 'lucide-react';

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    const [{ data: p }, { data: t }] = await Promise.all([
      supabase.from('projects').select('*').order('created_at', { ascending: false }),
      supabase.from('tasks').select('*').not('project_id', 'is', null),
    ]);
    if (p) setProjects(p);
    if (t) setTasks(t);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const selected = projects.find((p) => p.id === selectedId);
  const selectedTasks = tasks.filter((t) => t.project_id === selectedId);
  const doneTasks = selectedTasks.filter((t) => t.status === 'done').length;

  const statusColors: Record<string, string> = {
    active: 'bg-green-500/20 text-green-400',
    paused: 'bg-yellow-500/20 text-yellow-400',
    completed: 'bg-neutral-500/20 text-neutral-400',
  };

  return (
    <div className="flex gap-6 h-[calc(100vh-6rem)]">
      <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 content-start overflow-y-auto">
        {projects.map((project) => {
          const projTasks = tasks.filter((t) => t.project_id === project.id);
          const projDone = projTasks.filter((t) => t.status === 'done').length;
          return (
            <button
              key={project.id}
              onClick={() => setSelectedId(project.id)}
              className={`text-left bg-[#141414] border rounded-lg p-4 transition-colors duration-150 ${
                selectedId === project.id ? 'border-neutral-600' : 'border-neutral-800 hover:border-neutral-700'
              }`}
            >
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <FolderKanban size={14} className="text-neutral-500" />
                  <h3 className="text-sm font-medium text-neutral-200">{project.name}</h3>
                </div>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${statusColors[project.status]}`}>
                  {project.status}
                </span>
              </div>
              {project.description && (
                <p className="text-xs text-neutral-500 mb-3 line-clamp-2">{project.description}</p>
              )}
              <div className="mb-2">
                <div className="flex items-center justify-between text-[10px] text-neutral-500 mb-1">
                  <span>Progress</span>
                  <span>{project.progress}%</span>
                </div>
                <div className="w-full bg-neutral-800 rounded-full h-1.5">
                  <div
                    className="bg-neutral-400 h-1.5 rounded-full transition-all duration-300"
                    style={{ width: `${project.progress}%` }}
                  />
                </div>
              </div>
              <div className="flex items-center justify-between text-[10px] text-neutral-600">
                <span>{projDone}/{projTasks.length} tasks done</span>
                <span>{formatDistanceToNow(new Date(project.updated_at), { addSuffix: true })}</span>
              </div>
            </button>
          );
        })}
        {projects.length === 0 && (
          <p className="text-sm text-neutral-600 col-span-full text-center py-8">No projects yet</p>
        )}
      </div>

      {/* Detail panel */}
      {selected && (
        <div className="hidden lg:flex flex-col w-80 flex-shrink-0 bg-[#141414] border border-neutral-800 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-neutral-800">
            <h2 className="text-sm font-medium text-neutral-200">{selected.name}</h2>
            {selected.description && <p className="text-xs text-neutral-500 mt-1">{selected.description}</p>}
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            <h3 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">
              Tasks ({doneTasks}/{selectedTasks.length})
            </h3>
            <div className="space-y-1.5">
              {selectedTasks.map((t) => (
                <div key={t.id} className="flex items-center gap-2 text-xs">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                    t.status === 'done' ? 'bg-green-500' : t.status === 'in_progress' ? 'bg-blue-500' : 'bg-neutral-600'
                  }`} />
                  <span className={`truncate ${t.status === 'done' ? 'text-neutral-500 line-through' : 'text-neutral-300'}`}>
                    {t.title}
                  </span>
                </div>
              ))}
              {selectedTasks.length === 0 && (
                <p className="text-xs text-neutral-600">No tasks linked</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
