'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  Calendar,
  Brain,
  FileText,
  FolderKanban,
  DollarSign,
  Workflow,
  Activity,
} from 'lucide-react';

const NAV_ITEMS = [
  { href: '/tasks', label: 'Tasks', icon: LayoutDashboard },
  { href: '/calendar', label: 'Calendar', icon: Calendar },
  { href: '/memory', label: 'Memory', icon: Brain },
  { href: '/documents', label: 'Documents', icon: FileText },
  { href: '/projects', label: 'Projects', icon: FolderKanban },
  { href: '/costs', label: 'Costs', icon: DollarSign },
  { href: '/pipeline', label: 'Pipeline', icon: Workflow },
  { href: '/health', label: 'Health', icon: Activity },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden md:flex flex-col w-56 border-r border-neutral-800 bg-[#0a0a0a] h-screen fixed left-0 top-0 z-40">
        <div className="px-4 py-5 border-b border-neutral-800">
          <h1 className="text-sm font-semibold text-neutral-200 tracking-wide">Mission Control</h1>
          <p className="text-xs text-neutral-500 mt-0.5">armandito + sol-bot</p>
        </div>
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors duration-150 ${
                  isActive
                    ? 'bg-neutral-800 text-neutral-100'
                    : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/50'
                }`}
              >
                <item.icon size={16} />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Mobile bottom nav */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-[#0a0a0a] border-t border-neutral-800 flex justify-around py-2">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex flex-col items-center gap-0.5 px-2 py-1 text-xs transition-colors duration-150 ${
                isActive ? 'text-neutral-100' : 'text-neutral-500'
              }`}
            >
              <item.icon size={18} />
              <span className="truncate max-w-[3rem]">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
