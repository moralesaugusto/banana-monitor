import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { AiConfigPage } from './AiConfigPage'

const settings = {
  enabled: false, system_prompt: '', model_override: '', llm_base_url: 'http://agents/v1', llm_model: 'agent-m',
  llm_provider: 'ollama',
  llm_credential_id: null, llm_call_timeout_seconds: 120, max_iterations: 15, temperature: 0.2, max_targets: 25,
  enabled_tools: ['run_nmap'], allow_undefined_network_scan: false, undefined_scan_max_hosts: 256,
  allow_public_targets: false, cred_allow_unlisted_hosts: false, cred_no_attempt_limit: false,
  cred_trust_new_host_keys: false, cred_pool_for_updates: false, ollama_max_concurrent_calls: 2, openrouter_max_concurrent_calls: 4,
  memory_max_entries_per_agent: 30, memory_max_content_chars: 500, memory_max_inject_chars: 2000,
}

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AiConfigPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AiConfigPage', () => {
  beforeEach(() => {
    queryClient.clear()
    server.use(
      http.get('/api/ai-mode/settings', () => HttpResponse.json(settings)),
      http.get('/api/ai-mode/tools', () => HttpResponse.json({ default_system_prompt: 'default prompt', tools: [], guardrails: [], allowed_nmap_flags: '' })),
      http.get('/api/ai-mode/custom-tools', () => HttpResponse.json([])),
      http.get('/api/assistant/config', () => HttpResponse.json({ provider: 'ollama', base_url: 'http://x/v1', model: 'm', credential_id: null, max_tool_iterations: 8, llm_timeout_seconds: 120, full_access: false })),
      http.get('/api/assistant/tools', () =>
        HttpResponse.json({
          tools: [
            { name: 'get_overview', description: 'Get platform-wide status counts.', parameters: {}, write: false, enabled: true },
            { name: 'update_device', description: 'Update a device.', parameters: {}, write: true, enabled: false },
          ],
        }),
      ),
      http.get('/api/system/internet-access', () => HttpResponse.json({ blocked: false, agents: ['sinverguenza'] })),
    )
  })

  it('shows the Settings tabs, defaulting to General, with no Master Discoverer fields', async () => {
    renderPage()
    expect(await screen.findByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByLabelText('Enable AI Mode')).toBeInTheDocument()
    expect(screen.queryByText('Master Discoverer: model')).not.toBeInTheDocument()
    expect(screen.queryByText('Master Discoverer: system prompt')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Max targets per run')).not.toBeInTheDocument()
  })

  it('saves the Enable AI Mode switch from the General tab', async () => {
    let saved: Record<string, unknown> | null = null
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByLabelText('Enable AI Mode'))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(saved).toMatchObject({ enabled: true }))
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('saves the undefined-network scan settings from the Discovery tab', async () => {
    let saved: Record<string, unknown> | null = null
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('tab', { name: 'Discovery' }))
    await user.click(screen.getByText(/Allow scanning private \(RFC1918\)/))
    const limit = screen.getByLabelText(/Host limit for those out-of-network sweeps/)
    await user.clear(limit)
    await user.type(limit, '64')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(saved).toMatchObject({ allow_undefined_network_scan: true, undefined_scan_max_hosts: 64 }),
    )
  })

  it('saves allow_public_targets as its own disclaimed opt-in on the Discovery tab, off by default', async () => {
    let saved: Record<string, unknown> | null = null
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('tab', { name: 'Discovery' }))
    const checkbox = await screen.findByLabelText(/allow agents to target publicly routable addresses/i)
    expect(checkbox).not.toBeChecked()
    expect(screen.getByText(/attack surface on a network that is very likely not yours/i)).toBeInTheDocument()

    await user.click(checkbox)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(saved).toMatchObject({ allow_public_targets: true }))
  })

  it('saves the default LLM for agents and tests it as an Ollama connection', async () => {
    let saved: Record<string, unknown> | null = null
    let tested: unknown
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved })
      }),
      http.post('/api/ai-mode/agents/test-connection', async ({ request }) => {
        tested = await request.json()
        return HttpResponse.json({ ok: true, checks: [{ id: 'host', status: 'ok', title: 'Host answers', detail: '' }] })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const model = await screen.findByDisplayValue('agent-m')
    await user.clear(model)
    await user.type(model, 'agent-2')
    await user.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText('Host answers')).toBeInTheDocument()
    expect(tested).toEqual({
      provider: 'ollama',
      base_url: 'http://agents/v1',
      model: 'agent-2',
      credential_id: null,
      timeout_seconds: 120,
    })

    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(saved).toMatchObject({ llm_model: 'agent-2', llm_base_url: 'http://agents/v1' }))
  })

  it('saves a cost budget, alongside the default LLM', async () => {
    let saved: Record<string, unknown> | null = null
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const budget = await screen.findByLabelText(/Cost budget/)
    await user.type(budget, '25')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(saved).toMatchObject({ cost_budget_usd: 25 }))
  })

  it('switches the agents default to OpenRouter and saves it with a new key credential', async () => {
    let saved: Record<string, unknown> | null = null
    let credential: unknown
    server.use(
      http.post('/api/credentials', async ({ request }) => {
        credential = await request.json()
        return HttpResponse.json({ id: 42 })
      }),
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.selectOptions(await screen.findByLabelText('Provider'), 'openrouter')
    await user.type(screen.getByPlaceholderText('sk-or-...'), 'sk-or-secret')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(saved).toMatchObject({
        llm_provider: 'openrouter',
        llm_credential_id: 42,
        llm_base_url: 'https://openrouter.ai/api/v1',
      }),
    )
    expect(credential).toMatchObject({ secret: { token: 'sk-or-secret' } })
    expect(JSON.stringify(saved)).not.toContain('sk-or-secret')
  })

  it('picks an already-stored OpenRouter key for the agents\' default instead of pasting a new one', async () => {
    let saved: Record<string, unknown> | null = null
    let posted: unknown = null
    server.use(
      http.get('/api/credentials', () =>
        HttpResponse.json([
          {
            id: 9,
            label: 'OpenRouter API key',
            credential_type: 'api_token',
            created_at: '',
            rotated_at: null,
            last_used_at: null,
            used_by: [],
          },
        ]),
      ),
      http.post('/api/credentials', async ({ request }) => {
        posted = await request.json()
        return HttpResponse.json({ id: 42 })
      }),
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.selectOptions(await screen.findByLabelText('Provider'), 'openrouter')
    await user.selectOptions(await screen.findByLabelText('Stored OpenRouter key'), '9')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(saved).toMatchObject({ llm_provider: 'openrouter', llm_credential_id: 9 }))
    expect(posted).toBeNull() // reused the stored credential - never minted a new one
  })

  it('tests the connection with an already-stored OpenRouter key, not just a freshly pasted one', async () => {
    let tested: unknown
    server.use(
      http.get('/api/credentials', () =>
        HttpResponse.json([
          {
            id: 9,
            label: 'OpenRouter API key',
            credential_type: 'api_token',
            created_at: '',
            rotated_at: null,
            last_used_at: null,
            used_by: [],
          },
        ]),
      ),
      http.post('/api/ai-mode/agents/test-connection', async ({ request }) => {
        tested = await request.json()
        return HttpResponse.json({ ok: true, checks: [{ id: 'key', status: 'ok', title: 'Key accepted', detail: '' }] })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.selectOptions(await screen.findByLabelText('Provider'), 'openrouter')
    await user.selectOptions(await screen.findByLabelText('Stored OpenRouter key'), '9')
    await user.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(await screen.findByText('Key accepted')).toBeInTheDocument()
    expect(tested).toMatchObject({ credential_id: 9 })
  })

  it('lists the assistant\'s tools, showing write tools as off until full access is ticked', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('tab', { name: 'Chat assistant' }))

    expect(await screen.findByText('get_overview')).toBeInTheDocument()
    expect(screen.getByText('update_device')).toBeInTheDocument()
    expect(screen.getAllByText('on')).toHaveLength(1) // only the read-only tool
    expect(screen.getAllByText('off')).toHaveLength(1) // the write tool, full access is off

    await user.click(screen.getByRole('checkbox', { name: /^Full access/ }))
    expect(screen.getAllByText('on')).toHaveLength(2) // updates immediately, before Save
  })

  it('edits the chat assistant connection from the Assistant tab', async () => {
    let saved: Record<string, unknown> | null = null
    server.use(
      http.put('/api/assistant/config', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...saved, credential_id: null })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('tab', { name: 'Chat assistant' }))
    const model = await screen.findByDisplayValue('m')
    await user.clear(model)
    await user.type(model, 'm2')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(saved).toMatchObject({ model: 'm2', base_url: 'http://x/v1' }))
  })

  it('defaults to read-only and saves full access once turned on', async () => {
    let saved: Record<string, unknown> | null = null
    server.use(
      http.put('/api/assistant/config', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...saved, credential_id: null })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('tab', { name: 'Chat assistant' }))
    const toggle = await screen.findByRole('checkbox', { name: 'Full access (god mode)' })
    expect(toggle).not.toBeChecked()
    expect(screen.getByText('Off (default): read-only. Save to apply.')).toBeInTheDocument()

    await user.click(toggle)
    expect(screen.getByText(/the assistant may use its write tools/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(saved).toMatchObject({ full_access: true }))
  })

  it('tunes the chat turn limits and the agents\' default model call timeout', async () => {
    const saved: Record<string, Record<string, unknown>> = {}
    server.use(
      http.put('/api/assistant/config', async ({ request }) => {
        saved.chat = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...saved.chat, credential_id: null })
      }),
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved.agents = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved.agents })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const agentTimeout = await screen.findByLabelText(/^Model call timeout/)
    await user.clear(agentTimeout)
    await user.type(agentTimeout, '600')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(saved.agents).toMatchObject({ llm_call_timeout_seconds: 600 }))

    await user.click(screen.getByRole('tab', { name: 'Chat assistant' }))
    const calls = await screen.findByLabelText(/^Model calls per chat turn/)
    await user.clear(calls)
    await user.type(calls, '20')
    const timeout = screen.getByLabelText('Model call timeout (seconds)')
    await user.clear(timeout)
    await user.type(timeout, '300')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(saved.chat).toMatchObject({ max_tool_iterations: 20, llm_timeout_seconds: 300 }))
  })

  it('saves the per-provider LLM call concurrency caps from the General tab', async () => {
    const saved: Record<string, Record<string, unknown>> = {}
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved.agents = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved.agents })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const ollama = await screen.findByLabelText(/^Max concurrent Ollama calls/)
    await user.clear(ollama)
    await user.type(ollama, '1')
    const openrouter = screen.getByLabelText(/^Max concurrent OpenRouter calls/)
    await user.clear(openrouter)
    await user.type(openrouter, '6')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(saved.agents).toMatchObject({
        ollama_max_concurrent_calls: 1,
        openrouter_max_concurrent_calls: 6,
      }),
    )
  })

  it('shows and edits the agent memory size settings as approximate tokens, saving as characters', async () => {
    const saved: Record<string, Record<string, unknown>> = {}
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved.agents = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved.agents })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    // 500 chars / 4 = 125 tokens; 2000 chars / 4 = 500 tokens (the fixture's defaults, converted).
    const perNote = await screen.findByLabelText(/^Max size per note/)
    expect(perNote).toHaveValue(125)
    const perCall = screen.getByLabelText(/^Max total injected per call/)
    expect(perCall).toHaveValue(500)

    await user.clear(perNote)
    await user.type(perNote, '100') // ~tokens in
    await user.clear(perCall)
    await user.type(perCall, '300')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(saved.agents).toMatchObject({
        memory_max_content_chars: 400, // converted back to characters (100 * 4) before the PUT
        memory_max_inject_chars: 1200, // 300 * 4
      }),
    )
  })

  it('fills in the OpenRouter endpoint and model when that provider is chosen, and restores Ollama after', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('tab', { name: 'Chat assistant' }))
    await userEvent.selectOptions(await screen.findByLabelText('Provider'), 'openrouter')

    expect(screen.getByLabelText('Base URL')).toHaveValue('https://openrouter.ai/api/v1')
    expect(screen.getByLabelText('Model')).toHaveValue('nvidia/nemotron-3.5-lightning:free')

    await userEvent.selectOptions(screen.getByLabelText('Provider'), 'ollama')
    expect(screen.getByLabelText('Base URL')).toHaveValue('http://x/v1')
    expect(screen.getByLabelText('Model')).toHaveValue('m')
  })

  it('tests the connection with the unsaved form values, including a typed OpenRouter key', async () => {
    let body: unknown
    server.use(
      http.post('/api/assistant/test', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          ok: false,
          checks: [{ id: 'model', status: 'fail', title: 'Model zzz is not available', detail: 'Available: m.' }],
        })
      }),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('tab', { name: 'Chat assistant' }))
    await userEvent.selectOptions(await screen.findByLabelText('Provider'), 'openrouter')
    await userEvent.type(screen.getByLabelText('API key'), 'sk-or-1')
    await userEvent.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(await screen.findByText('Model zzz is not available')).toBeInTheDocument()
    expect(body).toEqual({
      provider: 'openrouter',
      base_url: 'https://openrouter.ai/api/v1',
      model: 'nvidia/nemotron-3.5-lightning:free',
      timeout_seconds: 120,
      credential_id: null,
      api_key: 'sk-or-1',
    })
  })

  it('tests the chat assistant connection with an already-stored OpenRouter key', async () => {
    let body: unknown
    server.use(
      http.get('/api/credentials', () =>
        HttpResponse.json([
          {
            id: 9,
            label: 'OpenRouter API key',
            credential_type: 'api_token',
            created_at: '',
            rotated_at: null,
            last_used_at: null,
            used_by: [],
          },
        ]),
      ),
      http.post('/api/assistant/test', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ ok: true, checks: [{ id: 'key', status: 'ok', title: 'Key accepted', detail: '' }] })
      }),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('tab', { name: 'Chat assistant' }))
    await userEvent.selectOptions(await screen.findByLabelText('Provider'), 'openrouter')
    await userEvent.selectOptions(await screen.findByLabelText('Stored OpenRouter key'), '9')
    await userEvent.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(await screen.findByText('Key accepted')).toBeInTheDocument()
    expect(body).toMatchObject({ credential_id: 9 })
  })

  it('still shows the key field when the assistant is bound to a key the list would otherwise skip', async () => {
    server.use(
      http.get('/api/assistant/config', () =>
        HttpResponse.json({ provider: 'openrouter', base_url: 'https://openrouter.ai/api/v1', model: 'm', credential_id: 10, max_tool_iterations: 8, llm_timeout_seconds: 120, full_access: false }),
      ),
      http.get('/api/credentials', () =>
        HttpResponse.json([
          { id: 10, label: 'Proxmox token', credential_type: 'api_token', created_at: '', rotated_at: null, last_used_at: null, used_by: ['integration pve', 'the chat assistant'] },
        ]),
      ),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('tab', { name: 'Chat assistant' }))

    expect(await screen.findByLabelText('Stored OpenRouter key')).toHaveValue('10')
  })

  it('clears every agent\'s memory from the General tab, after confirming', async () => {
    let cleared = false
    server.use(
      http.delete('/api/ai-mode/memory', () => {
        cleared = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: "Clear all agents' memory" }))
    expect(confirm).toHaveBeenCalled()
    await waitFor(() => expect(cleared).toBe(true))
    expect(await screen.findByText('Cleared.')).toBeInTheDocument()
  })

  it('does not clear memory when the confirmation is declined', async () => {
    let cleared = false
    server.use(
      http.delete('/api/ai-mode/memory', () => {
        cleared = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: "Clear all agents' memory" }))
    expect(cleared).toBe(false)
  })

  it('shows the internet kill switch on the General tab (moved from the System page)', async () => {
    let blockedTo: boolean | null = null
    server.use(
      http.put('/api/system/internet-access', async ({ request }) => {
        const body = (await request.json()) as { blocked: boolean }
        blockedTo = body.blocked
        return HttpResponse.json({ blocked: body.blocked, agents: ['sinverguenza'] })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('Agent internet kill switch')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Block all agent internet access' }))
    await waitFor(() => expect(blockedTo).toBe(true))
  })

  it('shows the moved Cost tab and the new Performance tab', async () => {
    server.use(
      http.get('/api/ai-mode/cost', () =>
        HttpResponse.json({ since: null, first_day: null, totals: { calls: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, max_context_tokens: 0, calls_without_usage: 0 }, by_agent: [], by_model: [], by_day: [], actual_usd: 0 }),
      ),
      http.get('/api/ai-mode/performance', () =>
        HttpResponse.json({ since: null, by_agent: [], by_agent_model: [], by_model: [] }),
      ),
    )
    renderPage()

    await userEvent.click(await screen.findByRole('tab', { name: 'Cost' }))
    expect(await screen.findByText('Reset counters')).toBeInTheDocument()

    await userEvent.click(await screen.findByRole('tab', { name: 'Performance' }))
    expect((await screen.findAllByText(/No model calls recorded yet/)).length).toBe(3)
  })

  describe('API Keys tab', () => {
    const storedKey = {
      id: 9,
      label: 'OpenRouter API key (agents)',
      credential_type: 'api_token',
      created_at: '2026-11-17T00:00:00Z',
      rotated_at: null,
      last_used_at: null,
      used_by: [],
    }

    it('lists stored keys whatever their label, but not tokens owned by Telegram or an integration', async () => {
      server.use(
        http.get('/api/credentials', () =>
          HttpResponse.json([
            storedKey,
            { ...storedKey, id: 11, label: 'Artex' },
            { ...storedKey, id: 10, label: 'Telegram bot token', used_by: ['Telegram'] },
            { ...storedKey, id: 12, label: 'virustotal-key', used_by: ['integration VirusTotal'] },
          ]),
        ),
      )
      renderPage()

      await userEvent.click(await screen.findByRole('tab', { name: 'API Keys' }))

      expect(await screen.findByText('OpenRouter API key (agents)')).toBeInTheDocument()
      expect(screen.getByText('Artex')).toBeInTheDocument()
      expect(screen.queryByText('Telegram bot token')).not.toBeInTheDocument()
      expect(screen.queryByText('virustotal-key')).not.toBeInTheDocument()
    })

    it('adds a new OpenRouter key', async () => {
      let posted: Record<string, unknown> | null = null
      server.use(
        http.get('/api/credentials', () => HttpResponse.json([])),
        http.post('/api/credentials', async ({ request }) => {
          posted = (await request.json()) as Record<string, unknown>
          return HttpResponse.json({ ...storedKey, label: posted.label }, { status: 201 })
        }),
      )
      const user = userEvent.setup()
      renderPage()
      await user.click(await screen.findByRole('tab', { name: 'API Keys' }))

      await user.type(screen.getByPlaceholderText('e.g. OpenRouter - personal'), 'my new key')
      await user.type(screen.getByPlaceholderText('sk-or-...'), 'sk-or-brandnew')
      await user.click(screen.getByRole('button', { name: 'Add key' }))

      await waitFor(() =>
        expect(posted).toMatchObject({
          label: 'my new key',
          credential_type: 'api_token',
          secret: { token: 'sk-or-brandnew' },
        }),
      )
    })

    it('renames a stored key without touching its secret', async () => {
      let patched: Record<string, unknown> | null = null
      server.use(
        http.get('/api/credentials', () => HttpResponse.json([storedKey])),
        http.patch('/api/credentials/9', async ({ request }) => {
          patched = (await request.json()) as Record<string, unknown>
          return HttpResponse.json({ ...storedKey, label: patched.label })
        }),
      )
      const user = userEvent.setup()
      renderPage()
      await user.click(await screen.findByRole('tab', { name: 'API Keys' }))

      await user.click(await screen.findByRole('button', { name: 'Rename' }))
      const input = screen.getByDisplayValue('OpenRouter API key (agents)')
      await user.clear(input)
      await user.type(input, 'renamed key')
      await user.click(screen.getByRole('button', { name: 'Save name' }))

      await waitFor(() => expect(patched).toEqual({ label: 'renamed key' }))
    })

    it('blocks deleting a key that is still in use and shows what uses it', async () => {
      server.use(
        http.get('/api/credentials', () =>
          HttpResponse.json([{ ...storedKey, used_by: ["the agents' default LLM"] }]),
        ),
        http.delete('/api/credentials/9', () =>
          HttpResponse.json(
            { detail: "Credential is still used by the agents' default LLM. Change or remove those first." },
            { status: 409 },
          ),
        ),
      )
      const user = userEvent.setup()
      vi.spyOn(window, 'confirm').mockReturnValue(true)
      renderPage()
      await user.click(await screen.findByRole('tab', { name: 'API Keys' }))

      await user.click(await screen.findByRole('button', { name: 'Delete' }))

      expect(await screen.findByText(/still used by the agents' default LLM/)).toBeInTheDocument()
    })
  })

  it('relaxes a credential safeguard only after a warning, and saves it', async () => {
    let saved: Record<string, unknown> | null = null
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved })
      }),
    )
    const confirm = vi.spyOn(window, 'confirm')
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('tab', { name: 'Discovery' }))
    expect(screen.getByText(/All of these are on by default and should almost always stay on/)).toBeInTheDocument()
    const box = screen.getByLabelText(/Let agents trust an unseen SSH host key on first use/)
    expect(box).not.toBeChecked()

    confirm.mockReturnValueOnce(false)
    await user.click(box)
    expect(box).not.toBeChecked()
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('impersonating the target'))

    confirm.mockReturnValueOnce(true)
    await user.click(box)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(saved).toMatchObject({ cred_trust_new_host_keys: true, cred_no_attempt_limit: false }))
  })
})

