import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { AiConfigPage } from './AiConfigPage'

const settings = {
  enabled: false, system_prompt: '', model_override: '', llm_base_url: 'http://agents/v1', llm_model: 'agent-m',
  llm_provider: 'ollama',
  llm_credential_id: null, llm_call_timeout_seconds: 120, max_iterations: 15, temperature: 0.2, max_targets: 25,
  enabled_tools: ['run_nmap'], allow_undefined_network_scan: false, undefined_scan_max_hosts: 256,
  ollama_max_concurrent_calls: 2, openrouter_max_concurrent_calls: 4,
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

  it('saves the default LLM for agents and tests it as an Ollama connection', async () => {
    let saved: Record<string, unknown> | null = null
    let tested: unknown
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved })
      }),
      http.post('/api/assistant/test', async ({ request }) => {
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
      api_key: 'sk-or-1',
    })
  })

  it('shows the moved Cost tab and the new Performance tab', async () => {
    server.use(
      http.get('/api/ai-mode/cost', () =>
        HttpResponse.json({ since: null, first_day: null, totals: { calls: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, max_context_tokens: 0, calls_without_usage: 0 }, by_agent: [], by_model: [], by_day: [] }),
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
})
