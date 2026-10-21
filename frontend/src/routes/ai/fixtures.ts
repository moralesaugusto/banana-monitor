import { http, HttpResponse } from 'msw'
import type { Agent } from '../../api/aiMode'
import { server } from '../../test/mswServer'

export const agent = (id: number, name: string, extra: Partial<Agent> = {}): Agent => ({
  id,
  name,
  display_name: null,
  role: `${name} role`,
  system_prompt: `You are ${name}.`,
  base_url: '',
  provider: '',
  credential_id: null,
  model_override: '',
  temperature: 0.2,
  max_iterations: 10,
  enabled_tools: ['publish_message'],
  mcp_url_override: null,
  mcp_timeout_seconds: 0,
  subscribes: [`task.${name}`],
  publishes: ['result.#'],
  require_approval: 'none',
  enabled: true,
  allow_changes: false,
  ...extra,
})

export const status = (agents: { name: string; state: string }[]) => ({
  ai_enabled: true,
  run: null,
  last_run: null,
  agents: agents.map((a) => ({ enabled: true, display_name: null, queued: 0, ...a })),
  schedule: {
    schedule_enabled: false, schedule_interval_seconds: 3600, schedule_entry_agent: 'discoverer', max_run_minutes: 20,
    max_targets: 25, llm_call_timeout_seconds: 120, last_scheduled_at: null, next_run_at: null,
  },
})

export const TOOLS = [
  { name: 'ssh_readonly', description: 'Run ONE read-only command on a Linux host. More text.', parameters: {}, enabled: false },
  { name: 'apply_updates', description: 'Install pending package updates. A human approves.', parameters: {}, enabled: false },
  { name: 'web_search', description: 'Search the internet.', parameters: {}, enabled: false },
  { name: 'publish_message', description: 'Publish a message to a topic.', parameters: {}, enabled: false },
]

/** An in-memory agents API: GET/POST/PUT/DELETE behave like the real one, so saves show up in the list. */
export function agentsApi(initial: Agent[], states: { name: string; state: string }[] = []) {
  const agents = [...initial]
  const calls: string[] = []
  server.use(
    http.get('/api/ai-mode/agents', () => HttpResponse.json(agents)),
    http.get('/api/ai-mode/status', () => HttpResponse.json(status(states))),
    http.get('/api/ai-mode/tools', () =>
      HttpResponse.json({ default_system_prompt: '', tools: TOOLS, guardrails: [], allowed_nmap_flags: '' }),
    ),
    http.get('/api/ai-mode/custom-tools', () => HttpResponse.json([])),
    http.get('/api/ai-mode/performance', () =>
      HttpResponse.json({ since: null, by_agent: [], by_agent_model: [], by_model: [] }),
    ),
    http.get('/api/ai-mode/settings', () =>
      HttpResponse.json({
        enabled: true, system_prompt: '', model_override: '', llm_base_url: 'http://default:11434/v1', llm_model: 'gpt', llm_provider: 'ollama', llm_credential_id: null,
        max_iterations: 15, temperature: 0.2, max_targets: 25, enabled_tools: [],
        allow_undefined_network_scan: false, undefined_scan_max_hosts: 256,
      }),
    ),
    http.post('/api/ai-mode/agents', async ({ request }) => {
      const body = (await request.json()) as Omit<Agent, 'id'>
      calls.push('POST agents')
      const saved = { id: agents.length + 10, ...body }
      agents.push(saved)
      return HttpResponse.json(saved, { status: 201 })
    }),
    http.put('/api/ai-mode/agents/:id', async ({ request, params }) => {
      const body = (await request.json()) as Omit<Agent, 'id'>
      calls.push(`PUT agents/${params.id}`)
      const saved = { id: Number(params.id), ...body }
      agents.splice(agents.findIndex((a) => a.id === saved.id), 1, saved)
      return HttpResponse.json(saved)
    }),
    http.delete('/api/ai-mode/agents/:id', ({ params }) => {
      calls.push(`DELETE agents/${params.id}`)
      agents.splice(agents.findIndex((a) => a.id === Number(params.id)), 1)
      return new HttpResponse(null, { status: 204 })
    }),
    http.post('/api/ai-mode/agents/:id/start', async ({ request, params }) => {
      const body = (await request.json()) as { targets: string[]; message: string | null }
      calls.push(`POST agents/${params.id}/start ${JSON.stringify(body)}`)
      return HttpResponse.json({ status: 'started', run_id: 1 }, { status: 202 })
    }),
  )
  return { agents, calls }
}
