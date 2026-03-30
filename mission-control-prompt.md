# Mission Control Dashboard - Prompt para Construir

> Copia y pega este prompt en cualquier agente de AI (Codex, Claude Code, ChatGPT, etc.) para construir tu Mission Control Dashboard.

---

## PROMPT

Construye un Mission Control Dashboard completo para mis dos bots: **armandito** (asistente personal en Telegram) y **sol-bot** (publicador automatizado de noticias para X/Twitter + Threads).

### Stack Tecnológico
- **Frontend**: Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS v4
- **Backend/DB**: Supabase (PostgreSQL + Realtime + RLS)
- **AI Model Routing**: OpenRouter API (`https://openrouter.ai/api/v1/chat/completions`, compatible con OpenAI SDK)
- **Charts**: Recharts
- **Icons**: Lucide React
- **Markdown**: react-markdown
- **UI Style**: Limpio, minimalista, estilo Linear. Dark mode por defecto. Sin emojis. Fuente mono.
- **Hosting**: localhost:3000

### Variables de Entorno (.env.local)
```
NEXT_PUBLIC_SUPABASE_URL=tu_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=tu_anon_key
SUPABASE_SERVICE_ROLE_KEY=tu_service_role_key
OPENROUTER_API_KEY=tu_api_key
```

---

## 8 PANTALLAS

### 1. Task Board (`/tasks`)
- Kanban board con 4 columnas: **Backlog → In Progress → Review → Done**
- Drag and drop entre columnas (actualiza Supabase en tiempo real)
- Cada card muestra: título, descripción truncada, badge de asignado (armandito/sol-bot/usuario), prioridad (color coded: rojo=urgent, naranja=high, azul=medium, gris=low), fecha relativa
- **Live Activity Feed** en sidebar derecho: últimas 50 acciones de los bots con timestamp, scroll infinito
- Botón "New Task" abre modal con formulario (título, descripción, asignado, prioridad, proyecto)
- **Realtime**: Supabase Realtime subscription para que cambios aparezcan sin refresh
- Tabla: `tasks`

### 2. Calendar (`/calendar`)
- Vista **mensual** (default) y **semanal** (toggle)
- Muestra cron jobs y tareas programadas de ambos bots
- **Color coding**: azul = armandito, naranja = sol-bot, verde = usuario
- Click en evento abre panel lateral con: nombre, cron expression legible, descripción, última ejecución, próxima ejecución, estado (activo/inactivo)
- Indicador de **quiet hours** (23:00-08:00) sombreado en gris en vista semanal
- Tabla: `scheduled_tasks`

### 3. Memory (`/memory`)
- Vista de memorias organizadas por día (agrupadas con header de fecha)
- **Búsqueda full-text** con debounce de 300ms
- **Filtros**: por bot (armandito/sol-bot/todos), por tipo (conversation/long_term/context)
- Tags como badges clickeables para filtrar
- Sección separada "Long-term Memories" con toggle para expandir/colapsar
- **Límites visibles**: contador de líneas por día (máximo 200) y archivo (máximo 300) - patrón Atlas-Cowork
- Tabla: `memories`

### 4. Documents (`/documents`)
- Grid de cards con: título, categoría (badge), formato, bot que lo creó, fecha
- Click abre **vista formateada** con markdown render (react-markdown)
- **Búsqueda** por título y contenido
- **Filtros**: por categoría (newsletter, planning, architecture, report, draft, etc.), por formato (markdown, text, json), por bot, por rango de fechas
- Botón copiar contenido al clipboard
- Tabla: `documents`

### 5. Projects (`/projects`)
- Cards grandes con: nombre, descripción, **barra de progreso** (0-100%), estado (active/paused/completed)
- Dentro de cada proyecto: lista de tareas vinculadas (de tabla tasks con project_id), memorias relacionadas, documentos relacionados
- Click en proyecto abre vista detalle con tabs: Overview / Tasks / Docs
- Badge con conteo de tareas pendientes vs completadas
- Tabla: `projects` con relaciones a `tasks`

### 6. Cost Tracker (`/costs`)
- **KPI cards** en la parte superior: gasto hoy, gasto esta semana, gasto este mes, proyección mensual
- **Gráfica de línea** (recharts): costo por día de los últimos 30 días, con línea por bot
- **Gráfica de barras**: tokens consumidos por modelo (top 5 modelos)
- **Gráfica de dona**: distribución de gasto por bot (armandito vs sol-bot)
- **Alerta visual**: banner rojo cuando el gasto mensual supere umbral configurable (default $50)
- **Tabla detallada**: últimas 100 API calls con columnas: timestamp, bot, modelo, tokens in, tokens out, costo, descripción
- Tabla: `api_usage`

### 7. Content Pipeline (`/pipeline`)
- Vista del pipeline de sol-bot: **Draft → Generating → Ready → Publishing → Published / Failed**
- Cada publicación muestra: headline, contenido (truncado), plataforma (X/Threads/both), tipo (WIRE/DEBATE/ANALISIS/CONEXION), URLs de posts publicados (clickeables)
- **Filtros**: por plataforma, por estado, por tipo, por rango de fechas
- Cards de publicaciones fallidas destacadas en rojo con error_message visible
- Métricas de engagement (si disponibles): likes, retweets, replies desde campo JSONB
- Tabla: `publications`

### 8. Health Monitor (`/health`)
- Grid de cards por servicio: **Supabase, OpenRouter, Telegram API, X/Twitter, Threads**
- Cada card muestra: nombre, estado (healthy/degraded/down con dot de color), último response time en ms, último error (si existe), último check
- **Timeline**: últimos 24 checks por servicio como puntos en línea horizontal (verde/amarillo/rojo)
- **Endpoint `/api/health`**: API route que hace ping real a cada servicio y guarda resultado en Supabase (sirve como keep-alive para evitar pausa del free tier)
- Auto-refresh cada 60 segundos
- Tabla: `health_checks`

---

## SUPABASE SCHEMA

Ejecutar este SQL en el SQL Editor de Supabase:

```sql
-- Projects (crear primero por la FK de tasks)
create table projects (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  description text,
  status text default 'active' check (status in ('active', 'paused', 'completed')),
  progress integer default 0 check (progress >= 0 and progress <= 100),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Tasks
create table tasks (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text,
  status text default 'backlog' check (status in ('backlog', 'in_progress', 'review', 'done')),
  assigned_to text default 'user' check (assigned_to in ('user', 'armandito', 'sol-bot')),
  priority text default 'medium' check (priority in ('low', 'medium', 'high', 'urgent')),
  project_id uuid references projects(id) on delete set null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Scheduled Tasks / Cron Jobs
create table scheduled_tasks (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  cron_expression text not null,
  bot text not null check (bot in ('armandito', 'sol-bot')),
  description text,
  last_run timestamptz,
  next_run timestamptz,
  is_active boolean default true,
  created_at timestamptz default now()
);

-- Memories
create table memories (
  id uuid primary key default gen_random_uuid(),
  content text not null,
  bot text not null check (bot in ('armandito', 'sol-bot')),
  memory_type text default 'conversation' check (memory_type in ('conversation', 'long_term', 'context')),
  tags text[],
  created_at timestamptz default now()
);

-- Documents
create table documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  content text not null,
  category text,
  format text default 'markdown',
  bot text not null check (bot in ('armandito', 'sol-bot')),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- API Usage / Cost Tracking
create table api_usage (
  id uuid primary key default gen_random_uuid(),
  bot text not null check (bot in ('armandito', 'sol-bot')),
  model text not null,
  provider text default 'openrouter',
  tokens_input integer not null,
  tokens_output integer not null,
  cost_usd numeric(10,6) not null,
  task_description text,
  created_at timestamptz default now()
);

-- Activity Log
create table activity_log (
  id uuid primary key default gen_random_uuid(),
  bot text not null check (bot in ('armandito', 'sol-bot')),
  action text not null,
  details jsonb,
  created_at timestamptz default now()
);

-- Content Pipeline (sol-bot publications)
create table publications (
  id uuid primary key default gen_random_uuid(),
  headline text not null,
  content text not null,
  platform text not null check (platform in ('x', 'threads', 'both')),
  status text default 'draft' check (status in ('draft', 'generating', 'ready', 'publishing', 'published', 'failed')),
  tweet_type text check (tweet_type in ('WIRE', 'DEBATE', 'ANALISIS', 'CONEXION')),
  x_post_url text,
  threads_post_url text,
  engagement jsonb default '{}',
  error_message text,
  created_at timestamptz default now(),
  published_at timestamptz
);

-- Health Checks
create table health_checks (
  id uuid primary key default gen_random_uuid(),
  service text not null,
  status text not null check (status in ('healthy', 'degraded', 'down')),
  response_time_ms integer,
  error_message text,
  checked_at timestamptz default now()
);

-- Indexes for performance
create index idx_tasks_status on tasks(status);
create index idx_tasks_assigned on tasks(assigned_to);
create index idx_memories_bot on memories(bot);
create index idx_memories_type on memories(memory_type);
create index idx_memories_created on memories(created_at desc);
create index idx_documents_category on documents(category);
create index idx_documents_bot on documents(bot);
create index idx_api_usage_bot on api_usage(bot);
create index idx_api_usage_created on api_usage(created_at desc);
create index idx_api_usage_model on api_usage(model);
create index idx_activity_log_bot on activity_log(bot);
create index idx_activity_log_created on activity_log(created_at desc);
create index idx_publications_status on publications(status);
create index idx_publications_platform on publications(platform);
create index idx_health_checks_service on health_checks(service);
create index idx_health_checks_checked on health_checks(checked_at desc);

-- Enable RLS on all tables
alter table tasks enable row level security;
alter table scheduled_tasks enable row level security;
alter table memories enable row level security;
alter table documents enable row level security;
alter table projects enable row level security;
alter table api_usage enable row level security;
alter table activity_log enable row level security;
alter table publications enable row level security;
alter table health_checks enable row level security;

-- Policies: allow all operations for anon key (single-user dashboard)
-- In production, replace with proper auth policies
create policy "Allow all on tasks" on tasks for all using (true) with check (true);
create policy "Allow all on scheduled_tasks" on scheduled_tasks for all using (true) with check (true);
create policy "Allow all on memories" on memories for all using (true) with check (true);
create policy "Allow all on documents" on documents for all using (true) with check (true);
create policy "Allow all on projects" on projects for all using (true) with check (true);
create policy "Allow all on api_usage" on api_usage for all using (true) with check (true);
create policy "Allow all on activity_log" on activity_log for all using (true) with check (true);
create policy "Allow all on publications" on publications for all using (true) with check (true);
create policy "Allow all on health_checks" on health_checks for all using (true) with check (true);

-- Enable Realtime for key tables
alter publication supabase_realtime add table tasks;
alter publication supabase_realtime add table activity_log;
alter publication supabase_realtime add table publications;
alter publication supabase_realtime add table health_checks;

-- Auto-cleanup function: delete api_usage older than 90 days
create or replace function cleanup_old_api_usage()
returns void as $$
begin
  delete from api_usage where created_at < now() - interval '90 days';
  delete from activity_log where created_at < now() - interval '90 days';
  delete from health_checks where checked_at < now() - interval '30 days';
end;
$$ language plpgsql;
```

---

## OPENROUTER INTEGRATION

Crear `src/lib/openrouter.ts` con:

1. **Model routing por tipo de tarea**:
   - `simple` → `qwen/qwen3-coder:free` ($0)
   - `content` → `deepseek/deepseek-chat-v3-0324` ($0.25/$0.38 por 1M tokens)
   - `coding` → `anthropic/claude-sonnet-4` ($3/$15)
   - `reasoning` → `anthropic/claude-opus-4` ($5/$25)

2. **Escalamiento por tiers**: Si un modelo falla, escalar al siguiente tier automáticamente

3. **Circuit breaker** (patrón Atlas-Cowork): Hashear params de cada request. Si el mismo hash falla 3 veces consecutivas, abortar y loguear error en vez de seguir reintentando (evita el caso real de $60 quemados overnight por retry loops)

4. **Logging automático**: Cada call exitosa se loguea en Supabase tabla `api_usage` con: bot, modelo, tokens_input, tokens_output, cost_usd, task_description

---

## PATRONES DE SEGURIDAD (Atlas-Cowork)

1. **Memoria con límites duros**: Máximo 200 líneas por día, 300 líneas en archivo long-term. Mostrar contador en UI.
2. **Circuit breaker**: 3 fallos idénticos = abort (ver OpenRouter integration)
3. **Anti-loop**: Máximo 5 tool calls consecutivos por request
4. **Quiet hours**: 23:00-08:00 sin heartbeats ni notificaciones (configurable en Calendar)
5. **Auto-cleanup**: Función SQL que borra api_usage > 90 días, activity_log > 90 días, health_checks > 30 días
6. **Keep-alive**: Endpoint `/api/health` hace ping a Supabase periódicamente para evitar pausa del free tier (7 días inactividad)

---

## REQUISITOS DE UI

- Dark mode: fondo `#0a0a0a`, cards `#141414`, bordes `#262626`, texto `#e5e5e5`
- Sidebar fija a la izquierda con iconos de Lucide + labels
- Status indicator en header: dot verde = conectado a Supabase, rojo = desconectado
- Auto-refresh cada 30 segundos en pantallas con datos live (tasks, pipeline, health)
- Skeleton loaders mientras cargan datos
- Error boundaries en React: si Supabase está caído, mostrar mensaje útil, no crashear
- Responsive: sidebar colapsa en mobile a bottom nav
- Transiciones suaves (150ms) en hover y cambios de estado
