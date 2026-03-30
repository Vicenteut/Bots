import { supabase } from './supabase';
import { MODEL_TIERS, type ModelTier, type BotOnly } from './types';

const OPENROUTER_API_URL = 'https://openrouter.ai/api/v1/chat/completions';
const MAX_IDENTICAL_FAILURES = 3;

const failureMap = new Map<string, number>();

function hashParams(params: Record<string, unknown>): string {
  return JSON.stringify(params);
}

interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

interface OpenRouterResponse {
  choices: { message: { content: string } }[];
  usage: { prompt_tokens: number; completion_tokens: number };
  model: string;
}

export async function chatCompletion(
  messages: ChatMessage[],
  tier: ModelTier,
  bot: BotOnly,
  taskDescription?: string
): Promise<{ content: string; model: string; tokens_input: number; tokens_output: number; cost_usd: number } | null> {
  const tierConfig = MODEL_TIERS[tier];
  const paramHash = hashParams({ messages, model: tierConfig.model });

  const failures = failureMap.get(paramHash) || 0;
  if (failures >= MAX_IDENTICAL_FAILURES) {
    console.error(`Circuit breaker: ${tierConfig.name} blocked after ${MAX_IDENTICAL_FAILURES} identical failures`);
    return null;
  }

  try {
    const res = await fetch(OPENROUTER_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${process.env.OPENROUTER_API_KEY}`,
        'X-Title': 'Mission Control',
      },
      body: JSON.stringify({ model: tierConfig.model, messages }),
    });

    if (!res.ok) {
      failureMap.set(paramHash, failures + 1);

      const tiers: ModelTier[] = ['simple', 'content', 'coding', 'reasoning'];
      const currentIdx = tiers.indexOf(tier);
      if (currentIdx < tiers.length - 1) {
        console.warn(`${tierConfig.name} failed, escalating to ${MODEL_TIERS[tiers[currentIdx + 1]].name}`);
        return chatCompletion(messages, tiers[currentIdx + 1], bot, taskDescription);
      }
      return null;
    }

    failureMap.delete(paramHash);

    const data: OpenRouterResponse = await res.json();
    const tokens_input = data.usage?.prompt_tokens || 0;
    const tokens_output = data.usage?.completion_tokens || 0;
    const cost_usd = (tokens_input / 1_000_000) * tierConfig.cost_input + (tokens_output / 1_000_000) * tierConfig.cost_output;

    await supabase.from('api_usage').insert({
      bot,
      model: data.model || tierConfig.model,
      provider: 'openrouter',
      tokens_input,
      tokens_output,
      cost_usd,
      task_description: taskDescription || null,
    });

    return {
      content: data.choices[0]?.message?.content || '',
      model: data.model || tierConfig.model,
      tokens_input,
      tokens_output,
      cost_usd,
    };
  } catch (err) {
    failureMap.set(paramHash, failures + 1);
    console.error(`OpenRouter error (${tierConfig.name}):`, err);
    return null;
  }
}
