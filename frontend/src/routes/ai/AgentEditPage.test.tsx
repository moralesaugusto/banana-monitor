import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { VerifyResult } from '../../api/aiMode'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { AgentEditPage } from './AgentEditPage'
import { agent, agentsApi } from './fixtures'

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderAt(path: string) {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/ai/agents" element={<div>LIST</div>} />
          <Route path="/ai/agents/new" element={<AgentEditPage />} />
          <Route path="/ai/agents/:name" element={<div>DETAIL</div>} />
          <Route path="/ai/agents/:name/edit" element={<AgentEditPage />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const ready: VerifyResult = { ok: true, checks: [{ id: 'host', status: 'ok', title: 'Ollama host answers', detail: '' }] }
const broken: VerifyResult = {
  ok: false,
  checks: [
    { id: 'host', status: 'fail', title: 'Ollama host is not reachable', detail: 'http://gpu:11434/v1: refused' },
    { id: 'prompt', status: 'warn', title: 'No system prompt', detail: '' },
    { id: 'name', status: 'ok', title: 'Name is available', detail: '' },
  ],
}

/** Records every verify request (its query string and body) and answers with `result`. */
function verifyApi(result: VerifyResult, calls: string[]) {
  const requests: { query: string; body: Record<string, unknown> }[] = []
  server.use(
    http.post('/api/ai-mode/agents/verify', async ({ request }) => {
      calls.push('POST verify')
      requests.push({ query: new URL(request.url).search, body: (await request.json()) as Record<string, unknown> })
      return HttpResponse.json(result)
    }),
  )
  return requests
}

describe('AgentEditPage', () => {
  beforeEach(() => queryClient.clear())
  afterEach(() => vi.restoreAllMocks())

  it('creates a new agent that picks its own Ollama host and model, then shows it', async () => {
    const api = agentsApi([])
    server.use(
      http.get('/api/ai-mode/ollama-models', ({ request }) => {
        expect(new URL(request.url).searchParams.get('base_url')).toBe('http://gpu:11434/v1')
        return HttpResponse.json({ base_url: 'http://gpu:11434/v1', models: ['qwen3:8b'] })
      }),
    )
    const user = userEvent.setup()
    renderAt('/ai/agents/new')

    await user.type(await screen.findByPlaceholderText('reviewer'), 'summarizer')
    await user.type(screen.getByPlaceholderText('http://localhost:11434/v1'), 'http://gpu:11434/v1')
    await user.click(screen.getByRole('button', { name: 'Load models' }))
    expect(await screen.findByText('1 model(s) on http://gpu:11434/v1')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^Model \(empty/), 'qwen3:8b')
    await user.click(screen.getByRole('button', { name: 'Add agent' }))

    expect(await screen.findByText('DETAIL')).toBeInTheDocument()
    expect(api.agents[0]).toMatchObject({ name: 'summarizer', base_url: 'http://gpu:11434/v1', model_override: 'qwen3:8b' })
    expect(screen.getByTestId('where')).toHaveTextContent('/ai/agents/summarizer')
  })

  it('puts one agent on OpenRouter with its own key while the default stays Ollama', async () => {
    const api = agentsApi([agent(1, 'reviewer')])
    let credential: unknown
    server.use(
      http.post('/api/credentials', async ({ request }) => {
        credential = await request.json()
        return HttpResponse.json({ id: 7 })
      }),
    )
    const user = userEvent.setup()
    renderAt('/ai/agents/reviewer/edit')

    await user.selectOptions(await screen.findByLabelText(/^Provider/), 'openrouter')
    await user.type(screen.getByPlaceholderText('sk-or-...'), 'sk-or-secret')
    await user.type(screen.getByLabelText(/^Model \(empty/), 'x/y:free')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.agents[0]).toMatchObject({ provider: 'openrouter', credential_id: 7, model_override: 'x/y:free' }),
    )
    expect(credential).toMatchObject({ secret: { token: 'sk-or-secret' } })
    expect(JSON.stringify(api.agents[0])).not.toContain('sk-or-secret')
  })

  it('sets a display name shown in the UI instead of the raw name, independent of Enabled', async () => {
    const api = agentsApi([agent(1, 'discoverer', { role: 'Finds open ports' })])
    const user = userEvent.setup()
    renderAt('/ai/agents/discoverer/edit')

    expect(await screen.findByRole('heading', { name: 'Edit discoverer' })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^Display name/), 'Master Discoverer')
    expect(screen.getByLabelText(/^Enabled/)).toBeChecked() // unaffected by the display name
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.agents[0]).toMatchObject({ display_name: 'Master Discoverer', enabled: true }))
  })

  it('opens an existing agent on its own screen with every setting filled in', async () => {
    agentsApi([agent(1, 'bellaco', { role: 'Health', enabled_tools: ['ssh_readonly'], temperature: 0.7, allow_changes: true })])
    renderAt('/ai/agents/bellaco/edit')

    expect(await screen.findByRole('heading', { name: 'Edit bellaco' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('reviewer')).toBeDisabled() // names are fixed
    expect(screen.getByDisplayValue('Health')).toBeInTheDocument()
    expect(screen.getByDisplayValue('0.7')).toBeInTheDocument()
    expect(screen.getByLabelText(/^May change hosts/)).toBeChecked()
    expect(await screen.findByRole('checkbox', { name: /^ssh_readonly/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /^web_search/ })).not.toBeChecked()
    // tools are grouped, described, and internet and changing tools are flagged
    expect(screen.getByText('Host inspection')).toBeInTheDocument()
    expect(screen.getByText('Run ONE read-only command on a Linux host.')).toBeInTheDocument()
    expect(screen.getByText('internet')).toBeInTheDocument()
    expect(screen.getByText('changes hosts')).toBeInTheDocument()
  })

  it('shows previous performance for a typed model, or that none is recorded yet', async () => {
    agentsApi([agent(1, 'bellaco')])
    server.use(
      http.get('/api/ai-mode/performance', () =>
        HttpResponse.json({
          since: null,
          by_agent: [],
          by_agent_model: [],
          by_model: [
            {
              model: 'qwen3:8b', agents: ['sinverguenza', 'reporter'], calls: 5,
              avg_duration_ms: 4_200, min_duration_ms: 1_000, max_duration_ms: 9_000,
              prompt_tokens: 1_000, completion_tokens: 200, tokens_per_second: 12.5,
            },
          ],
        }),
      ),
    )
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    const model = await screen.findByLabelText(/^Model \(empty/)
    await user.type(model, 'qwen3:8b')
    expect(await screen.findByText(/Used before \(by sinverguenza, reporter\)/)).toBeInTheDocument()
    expect(screen.getByText(/4\.2s per call, 12\.5 tok\/s over 5 call\(s\)/)).toBeInTheDocument()

    await user.clear(model)
    await user.type(model, 'brand-new-model')
    expect(await screen.findByText('No performance history yet for this model.')).toBeInTheDocument()
  })

  it('Verify checks the unsaved draft without saving it', async () => {
    const api = agentsApi([agent(1, 'bellaco')])
    const requests = verifyApi(broken, api.calls)
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    const role = await screen.findByDisplayValue('bellaco role')
    await user.clear(role)
    await user.type(role, 'new role')
    await user.click(screen.getByRole('button', { name: 'Verify' }))

    expect(await screen.findByText('1 problem to fix')).toBeInTheDocument()
    expect(screen.getByText('Ollama host is not reachable')).toBeInTheDocument()
    expect(screen.getByText('http://gpu:11434/v1: refused')).toBeInTheDocument()
    expect(screen.getByText('Problem')).toBeInTheDocument()
    expect(screen.getByText('Warning')).toBeInTheDocument()
    expect(requests).toHaveLength(1)
    expect(requests[0].query).toBe('?agent_id=1')
    expect(requests[0].body).toMatchObject({ name: 'bellaco', role: 'new role' })
    expect(api.calls).toEqual(['POST verify']) // nothing was saved
    expect(screen.getByRole('status')).toHaveTextContent('Unsaved changes')
  })

  it('Save and verify saves first, then verifies, and stays on the screen', async () => {
    const api = agentsApi([agent(1, 'bellaco')])
    const requests = verifyApi(ready, api.calls)
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    const role = await screen.findByDisplayValue('bellaco role')
    await user.clear(role)
    await user.type(role, 'new role')
    await user.click(screen.getByRole('button', { name: 'Save and verify' }))

    expect(await screen.findByText('Ready')).toBeInTheDocument()
    expect(api.calls).toEqual(['PUT agents/1', 'POST verify'])
    expect(requests[0].body).toMatchObject({ role: 'new role' })
    expect(screen.getByRole('status')).toHaveTextContent('Saved.')
    expect(screen.getByTestId('where')).toHaveTextContent('/ai/agents/bellaco/edit')
    expect(api.agents[0].role).toBe('new role')
  })

  it('Save saves and goes back to the agent', async () => {
    const api = agentsApi([agent(1, 'bellaco')])
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    await user.type(await screen.findByDisplayValue('bellaco role'), '!')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('DETAIL')).toBeInTheDocument()
    expect(api.calls).toEqual(['PUT agents/1'])
  })

  it('a new agent saved with verify keeps its results and moves to its edit address', async () => {
    const api = agentsApi([])
    verifyApi(ready, api.calls)
    const user = userEvent.setup()
    renderAt('/ai/agents/new')

    await user.type(await screen.findByPlaceholderText('reviewer'), 'scout')
    await user.click(screen.getByRole('button', { name: 'Save and verify' }))

    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/ai/agents/scout/edit'))
    expect(await screen.findByRole('heading', { name: 'Edit scout' })).toBeInTheDocument()
    expect(screen.getByText('Ready')).toBeInTheDocument()
    expect(api.calls).toEqual(['POST agents', 'POST verify'])
  })

  it('asks before discarding changes, and not when nothing changed', async () => {
    agentsApi([agent(1, 'bellaco')])
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(confirm).not.toHaveBeenCalled()
    expect(await screen.findByText('DETAIL')).toBeInTheDocument()
  })

  it('keeps the screen when discarding is declined, and leaves when accepted', async () => {
    agentsApi([agent(1, 'bellaco')])
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    await user.type(await screen.findByDisplayValue('bellaco role'), '!')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('heading', { name: 'Edit bellaco' })).toBeInTheDocument()

    confirm.mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(await screen.findByText('DETAIL')).toBeInTheDocument()
  })

  it('shows the server message when saving is refused', async () => {
    agentsApi([agent(1, 'bellaco')])
    server.use(
      http.put('/api/ai-mode/agents/:id', () =>
        HttpResponse.json({ detail: "['apply_updates'] change hosts: tick 'May change hosts' on this agent first" }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    await user.click(await screen.findByRole('checkbox', { name: /^apply_updates/ }))
    expect(screen.getByText(/also tick "May change hosts" under Safety/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('status')).toHaveTextContent("tick 'May change hosts' on this agent first")
    expect(screen.queryByText('DETAIL')).not.toBeInTheDocument()
  })

  it('says so when the address names no agent', async () => {
    agentsApi([agent(1, 'bellaco')])
    renderAt('/ai/agents/ghost/edit')

    expect(await screen.findByText('ghost')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to the agents' })).toBeInTheDocument()
  })
})
