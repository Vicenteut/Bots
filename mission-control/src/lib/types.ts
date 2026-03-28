export type TaskStatus = 'backlog' | 'in_progress' | 'review' | 'done';
export type Priority = 'low' | 'medium' | 'high' | 'urgent';
export type BotName = 'user' | 'armandito' | 'sol-bot';
export type BotOnly = 'armandito' | 'sol-bot';
export type MemoryType = 'conversation' | 'long_term' | 'context';
export type ProjectStatus = 'active' | 'paused' | 'completed';
export type PublicationStatus = 'draft' | 'generating' | 'ready' | 'publishing' | 'published' | 'failed';
export type TweetType = 'WIRE' | 'DEBATE' | 'ANALISIS' | 'CONEXION';
export type Platform = 'x' | 'threads' | 'both';
export type HealthStatus = 'healthy' | 'degraded' | 'down';
export type ModelTier = 'simple' | 'content' | 'coding' | 'reasoning';

export interface Task {
  id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  assigned_to: BotName;
  priority: Priority;
  project_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduledTask {
  id: string;
  name: string;
  cron_expression: string;
  bot: BotOnly;
  description: string | null;
  last_run: string | null;
  next_run: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Memory {
  id: string;
  content: string;
  bot: BotOnly;
  memory_type: MemoryType;
  tags: string[] | null;
  created_at: string;
}

export interface Document {
  id: string;
  title: string;
  content: string;
  category: string | null;
  format: string;
  bot: BotOnly;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  status: ProjectStatus;
  progress: number;
  created_at: string;
  updated_at: string;
}

export interface ApiUsage {
  id: string;
  bot: BotOnly;
  model: string;
  provider: string;
  tokens_input: number;
  tokens_output: number;
  cost_usd: number;
  task_description: string | null;
  created_at: string;
}

export interface ActivityLog {
  id: string;
  bot: BotOnly;
  action: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface Publication {
  id: string;
  headline: string;
  content: string;
  platform: Platform;
  status: PublicationStatus;
  tweet_type: TweetType | null;
  x_post_url: string | null;
  threads_post_url: string | null;
  engagement: Record<string, number>;
  error_message: string | null;
  created_at: string;
  published_at: string | null;
}

export interface HealthCheck {
  id: string;
  service: string;
  status: HealthStatus;
  response_time_ms: number | null;
  error_message: string | null;
  checked_at: string;
}

export const MODEL_TIERS: Record<ModelTier, { model: string; name: string; cost_input: number; cost_output: number }> = {
  simple: { model: 'qwen/qwen3-coder:free', name: 'Qwen3 Coder', cost_input: 0, cost_output: 0 },
  content: { model: 'deepseek/deepseek-chat-v3-0324', name: 'DeepSeek V3', cost_input: 0.25, cost_output: 0.38 },
  coding: { model: 'anthropic/claude-sonnet-4', name: 'Claude Sonnet 4', cost_input: 3, cost_output: 15 },
  reasoning: { model: 'anthropic/claude-opus-4', name: 'Claude Opus 4', cost_input: 5, cost_output: 25 },
};

export const PRIORITY_COLORS: Record<Priority, string> = {
  urgent: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  low: 'bg-neutral-500/20 text-neutral-400 border-neutral-500/30',
};

export const BOT_COLORS: Record<BotName, string> = {
  armandito: 'bg-blue-500/20 text-blue-400',
  'sol-bot': 'bg-orange-500/20 text-orange-400',
  user: 'bg-green-500/20 text-green-400',
};

export const STATUS_COLORS: Record<HealthStatus, string> = {
  healthy: 'bg-green-500',
  degraded: 'bg-yellow-500',
  down: 'bg-red-500',
};

export const PUBLICATION_STATUS_COLORS: Record<PublicationStatus, string> = {
  draft: 'bg-neutral-500/20 text-neutral-400',
  generating: 'bg-blue-500/20 text-blue-400',
  ready: 'bg-cyan-500/20 text-cyan-400',
  publishing: 'bg-yellow-500/20 text-yellow-400',
  published: 'bg-green-500/20 text-green-400',
  failed: 'bg-red-500/20 text-red-400',
};
