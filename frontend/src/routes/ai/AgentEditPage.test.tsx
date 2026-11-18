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
    await user.click(screen.getByRole('radio', { name: 'Custom' }))
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

    await user.click(await screen.findByRole('radio', { name: 'Custom' }))
    await user.selectOptions(screen.getByLabelText(/^Provider/), 'openrouter')
    await user.type(screen.getByPlaceholderText('sk-or-...'), 'sk-or-secret')
    await user.type(screen.getByLabelText(/^Model \(empty/), 'x/y:free')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.agents[0]).toMatchObject({ provider: 'openrouter', credential_id: 7, model_override: 'x/y:free' }),
    )
    expect(credential).toMatchObject({ secret: { token: 'sk-or-secret' } })
    expect(JSON.stringify(api.agents[0])).not.toContain('sk-or-secret')
  })

  it('lets you pick an already-stored OpenRouter key instead of pasting a new one', async () => {
    const api = agentsApi([agent(1, 'tajonaso')])
    let posted: unknown = null
    server.use(
      http.get('/api/credentials', () =>
        HttpResponse.json([
          {
            id: 9,
            label: 'OpenRouter API key (agents)',
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
        return HttpResponse.json({ id: 99 })
      }),
    )
    const user = userEvent.setup()
    renderAt('/ai/agents/tajonaso/edit')

    await user.click(await screen.findByRole('radio', { name: 'Custom' }))
    await user.selectOptions(screen.getByLabelText(/^Provider/), 'openrouter')
    await user.selectOptions(await screen.findByLabelText('Stored OpenRouter key'), '9')
    await user.type(screen.getByLabelText(/^Model \(empty/), 'x/y:free')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.agents[0]).toMatchObject({ credential_id: 9 }))
    expect(posted).toBeNull() // reused the stored credential - never minted a new one
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

  it('passes the picked provider to Load models, not just the base URL', async () => {
    agentsApi([agent(1, 'bellaco')])
    let seenProvider: string | null = null
    server.use(
      http.get('/api/ai-mode/ollama-models', ({ request }) => {
        seenProvider = new URL(request.url).searchParams.get('provider')
        return HttpResponse.json({ base_url: 'https://openrouter.ai/api/v1', models: ['anthropic/claude-3.5-sonnet'] })
      }),
    )
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    await user.click(await screen.findByRole('radio', { name: 'Custom' }))
    await user.selectOptions(screen.getByLabelText('Provider'), 'openrouter')
    await user.click(screen.getByRole('button', { name: 'Load models' }))

    await screen.findByText('1 model(s) on https://openrouter.ai/api/v1')
    expect(seenProvider).toBe('openrouter')
  })

  it('shows an OpenRouter-looking placeholder for the base URL once that provider is picked', async () => {
    const user = userEvent.setup()
    agentsApi([agent(1, 'bellaco')])
    renderAt('/ai/agents/bellaco/edit')

    await user.click(await screen.findByRole('radio', { name: 'Custom' }))
    expect(screen.getByPlaceholderText('http://localhost:11434/v1')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Provider'), 'openrouter')
    expect(screen.getByPlaceholderText('https://openrouter.ai/api/v1')).toBeInTheDocument()
  })

  it('tests the connection with this agent\'s own settings, same as the General/Assistant tabs', async () => {
    agentsApi([agent(1, 'bellaco', { provider: 'openrouter', model_override: 'anthropic/claude-3.5-sonnet' })])
    let sent: Record<string, unknown> | null = null
    server.use(
      http.post('/api/ai-mode/agents/test-connection', async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          ok: true,
          checks: [{ id: 'host', status: 'ok', title: 'Host answers', detail: '' }],
        })
      }),
    )
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    await user.click(await screen.findByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText('Host answers')).toBeInTheDocument()
    expect(sent).toMatchObject({ provider: 'openrouter', model: 'anthropic/claude-3.5-sonnet' })
  })

  it('blocks saving OpenRouter with no key configured anywhere, client-side', async () => {
    const api = agentsApi([agent(1, 'bellaco')])
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    await user.click(await screen.findByRole('radio', { name: 'Custom' }))
    await user.selectOptions(screen.getByLabelText('Provider'), 'openrouter')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/Enter an OpenRouter API key for this agent/)).toBeInTheDocument()
    expect(api.calls).toEqual([]) // never reached the network
  })

  it('puts the Remember checkbox and its overrides in Model, not Tools', async () => {
    const api = agentsApi([agent(1, 'bellaco', { enabled_tools: ['remember'] })])
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    expect(await screen.findByRole('heading', { name: 'Edit bellaco' })).toBeInTheDocument()
    const remember = screen.getByRole('checkbox', { name: /^Remember/ })
    expect(remember).toBeChecked()
    expect(screen.queryByRole('checkbox', { name: /^remember/ })).not.toBeInTheDocument() // not in Tools too
    expect(screen.getByLabelText(/Max notes kept/)).toBeInTheDocument() // overrides shown while ticked

    await user.click(remember)
    expect(screen.queryByLabelText(/Max notes kept/)).not.toBeInTheDocument() // hidden once unticked
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.agents[0].enabled_tools).not.toContain('remember'))
  })

  it('shows previous performance for the agent\'s saved model, not a live keystroke-by-keystroke draft', async () => {
    agentsApi([agent(1, 'bellaco', { provider: 'ollama', model_override: 'qwen3:8b' })])
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

    await user.click(await screen.findByRole('radio', { name: 'Custom' }))
    // Shown for the agent's saved model straight away, with nothing typed yet.
    expect(await screen.findByText(/Used before \(by sinverguenza, reporter\)/)).toBeInTheDocument()
    expect(screen.getByText(/4\.2s per call, 12\.5 tok\/s over 5 call\(s\)/)).toBeInTheDocument()

    // Typing a different, not-yet-saved model must not flicker the hint per keystroke - it stays
    // keyed to the saved model until the agent is actually saved again.
    const model = screen.getByLabelText(/^Model \(empty/)
    await user.clear(model)
    await user.type(model, 'brand-new-model')
    expect(screen.getByText(/Used before \(by sinverguenza, reporter\)/)).toBeInTheDocument()
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

describe('AgentEditPage connection mode', () => {
  beforeEach(() => queryClient.clear())
  afterEach(() => vi.restoreAllMocks())

  it('picks the Ollama or OpenRouter radio for a legacy blank-provider agent once the default loads', async () => {
    agentsApi([agent(1, 'bellaco')]) // provider: '' - the pre-existing "follows the default" shape
    renderAt('/ai/agents/bellaco/edit')
    await screen.findByRole('heading', { name: 'Edit bellaco' })

    await waitFor(() => expect(screen.getByRole('radio', { name: 'Use existing Ollama setting' })).toBeChecked())
    expect(screen.getByRole('radio', { name: 'Custom' })).not.toBeChecked()
  })

  it('stays on Custom even once every field in it is cleared back to blank', async () => {
    const user = userEvent.setup()
    agentsApi([agent(1, 'bellaco')])
    renderAt('/ai/agents/bellaco/edit')

    await user.click(await screen.findByRole('radio', { name: 'Custom' }))
    expect(screen.getByRole('radio', { name: 'Custom' })).toBeChecked()
    expect(screen.getByLabelText('Provider')).toHaveValue('ollama') // defaulted in, nothing else typed

    // Custom + Ollama + nothing else filled in is, by value, identical to "ollama_default" - the radio
    // selection must not silently flip back just because of that.
    expect(screen.getByRole('radio', { name: 'Custom' })).toBeChecked()
    expect(screen.getByLabelText(/^Model \(empty/)).toBeInTheDocument()
  })

  it('switching to "Use existing OpenRouter credentials" hides the host/key fields but keeps Model editable', async () => {
    const user = userEvent.setup()
    agentsApi([agent(1, 'bellaco', { provider: 'ollama', base_url: 'http://gpu:11434/v1', model_override: 'llama3' })])
    renderAt('/ai/agents/bellaco/edit')

    await user.click(await screen.findByRole('radio', { name: 'Use existing OpenRouter credentials' }))

    expect(screen.queryByLabelText('Provider')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText('http://gpu:11434/v1')).not.toBeInTheDocument()
    expect(screen.getByLabelText(/^Model(?!\scall)/)).toHaveValue('llama3') // kept, not cleared by the switch
  })

  it('links to Settings to assign the agents\' default OpenRouter key when none is set', async () => {
    const user = userEvent.setup()
    agentsApi([agent(1, 'bellaco')])
    renderAt('/ai/agents/bellaco/edit')

    await user.click(await screen.findByRole('radio', { name: 'Use existing OpenRouter credentials' }))

    expect(await screen.findByText(/OpenRouter - no key configured/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Settings/ })).toHaveAttribute('href', '/ai/config')
  })

  it('hides every field but Test connection under "Use existing Ollama setting"', async () => {
    const user = userEvent.setup()
    agentsApi([agent(1, 'bellaco', { provider: 'openrouter', model_override: 'x/y', base_url: 'https://x' })])
    renderAt('/ai/agents/bellaco/edit')

    await user.click(await screen.findByRole('radio', { name: 'Use existing Ollama setting' }))

    expect(screen.queryByLabelText('Provider')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^Model(?!\scall)/)).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText('sk-or-...')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Test connection' })).toBeInTheDocument()
  })

  it('saves an optional fallback model, retried once if the primary call fails', async () => {
    const api = agentsApi([agent(1, 'bellaco')])
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    expect(screen.queryByLabelText('Fallback model')).not.toBeInTheDocument() // off by default

    await user.click(await screen.findByRole('checkbox', { name: /Fallback model/ }))
    await user.selectOptions(screen.getByLabelText('Fallback provider'), 'ollama')
    await user.type(screen.getByLabelText('Fallback model'), 'llama3:70b')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.agents[0].fallback_provider).toBe('ollama'))
    expect(api.agents[0].fallback_model).toBe('llama3:70b')
  })

  it('unticking the fallback checkbox clears it back to unconfigured', async () => {
    const api = agentsApi([
      agent(1, 'bellaco', { fallback_provider: 'ollama', fallback_model: 'llama3:70b' }),
    ])
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    const toggle = await screen.findByRole('checkbox', { name: /Fallback model/ })
    expect(toggle).toBeChecked()
    expect(screen.getByLabelText('Fallback model')).toHaveValue('llama3:70b')

    await user.click(toggle)
    expect(screen.queryByLabelText('Fallback model')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.agents[0].fallback_provider).toBe(''))
    expect(api.agents[0].fallback_model).toBe('')
  })

  it('lets an agent use the credential pool or only selected credentials', async () => {
    server.use(
      http.get('/api/credentials', () =>
        HttpResponse.json([
          { id: 4, label: 'lab-ssh', credential_type: 'ssh_password', created_at: '2026-01-01T00:00:00Z', rotated_at: null, last_used_at: null, in_agent_pool: false, used_by: [] },
          { id: 5, label: 'nas-ssh', credential_type: 'ssh_key', created_at: '2026-01-01T00:00:00Z', rotated_at: null, last_used_at: null, in_agent_pool: true, used_by: [] },
        ]),
      ),
    )
    const api = agentsApi([agent(1, 'bellaco', { enabled_tools: ['ssh_readonly'] })])
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco/edit')

    expect(await screen.findByLabelText(/Host-bound integrations only/)).toBeChecked()
    await user.click(screen.getByLabelText(/Also try only the credentials I select/))
    await user.click(await screen.findByLabelText(/nas-ssh/))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.agents[0]).toMatchObject({ credential_scope: 'selected', credential_scope_ids: [5] }))
  })
})

