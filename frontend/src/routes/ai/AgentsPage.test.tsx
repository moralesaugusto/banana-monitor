import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { AgentsPage } from './AgentsPage'
import { agent, agentsApi } from './fixtures'

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderAt(path: string) {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/ai/agents" element={<AgentsPage />} />
          <Route path="/ai/agents/:name" element={<AgentsPage />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const bellaco = agent(1, 'bellaco', {
  role: 'Finds health problems',
  enabled_tools: ['ssh_readonly', 'apply_updates', 'web_search'],
  allow_changes: true,
  require_approval: 'tools',
  base_url: 'http://gpu:11434/v1',
  model_override: 'qwen3:8b',
  temperature: 0.4,
  max_iterations: 20,
  system_prompt: 'You are Bellaco, a system-health agent.',
})
const reporter = agent(2, 'reporter', { role: 'Writes reports', subscribes: ['task.reporter', 'result.bellaco'] })
const quiet = agent(3, 'quiet', { role: 'Sleeps', enabled: false })

describe('AgentsPage', () => {
  beforeEach(() => queryClient.clear())
  afterEach(() => vi.restoreAllMocks())

  it('lists every agent and shows ALL settings of the selected one', async () => {
    agentsApi([bellaco, reporter, quiet], [{ name: 'bellaco', state: 'working' }, { name: 'reporter', state: 'stopped' }])
    renderAt('/ai/agents')

    const list = within(await screen.findByRole('navigation', { name: 'Agents' }))
    expect(await list.findAllByRole('link')).toHaveLength(3)

    // The first agent is selected, and nothing is hidden behind a click.
    expect(screen.getByRole('heading', { name: 'bellaco' })).toBeInTheDocument()
    expect(screen.getByText('http://gpu:11434/v1')).toBeInTheDocument()
    expect(screen.getByText('qwen3:8b')).toBeInTheDocument()
    expect(screen.getByText('0.4')).toBeInTheDocument()
    expect(screen.getByText('up to 20 model calls per message')).toBeInTheDocument()
    expect(screen.getByText('Human approves its tool calls')).toBeInTheDocument()
    expect(screen.getByText('May change hosts; every change needs your approval')).toBeInTheDocument()
    expect(screen.getByText('You are Bellaco, a system-health agent.')).toBeInTheDocument()
    expect(screen.getByText('task.bellaco')).toBeInTheDocument()
    expect(screen.getByText('result.#')).toBeInTheDocument()
    for (const tool of ['ssh_readonly', 'apply_updates', 'web_search']) expect(screen.getByText(tool)).toBeInTheDocument()
    expect(screen.getByText('Host inspection')).toBeInTheDocument()
    expect(screen.getByText('Internet')).toBeInTheDocument()
    // Who reads its results is worked out from the other agents' subscriptions.
    const readers = screen.getByText('Results go to').nextElementSibling as HTMLElement
    expect(within(readers).getByText('reporter')).toBeInTheDocument()
  })

  it('selects an agent from the list and from the address', async () => {
    agentsApi([bellaco, reporter, quiet])
    const user = userEvent.setup()
    renderAt('/ai/agents/reporter')

    expect(await screen.findByRole('heading', { name: 'reporter' })).toBeInTheDocument()
    expect(screen.getByText('Read-only')).toBeInTheDocument()

    await user.click(within(screen.getByRole('navigation', { name: 'Agents' })).getByText('quiet'))
    expect(await screen.findByRole('heading', { name: 'quiet' })).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('/ai/agents/quiet')
    expect(screen.getByText('Switched off')).toBeInTheDocument()
  })

  it('searches by name, role and tool, and filters by state', async () => {
    agentsApi([bellaco, reporter, quiet], [{ name: 'bellaco', state: 'working' }, { name: 'reporter', state: 'stopped' }])
    const user = userEvent.setup()
    renderAt('/ai/agents')
    const nav = () => within(screen.getByRole('navigation', { name: 'Agents' }))
    await nav().findByText('reporter')

    await user.type(screen.getByRole('searchbox', { name: 'Search agents' }), 'ssh_read')
    expect(nav().getAllByRole('link')).toHaveLength(1)
    expect(nav().getByText('bellaco')).toBeInTheDocument()

    await user.clear(screen.getByRole('searchbox', { name: 'Search agents' }))
    await user.type(screen.getByRole('searchbox', { name: 'Search agents' }), 'writes')
    expect(nav().getAllByRole('link')).toHaveLength(1)
    expect(nav().getByText('reporter')).toBeInTheDocument()

    await user.clear(screen.getByRole('searchbox', { name: 'Search agents' }))
    await user.click(screen.getByRole('button', { name: 'Running' }))
    expect(nav().getAllByRole('link')).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: 'Disabled' }))
    expect(nav().getByText('quiet')).toBeInTheDocument()
    expect(nav().getAllByRole('link')).toHaveLength(1)

    await user.type(screen.getByRole('searchbox', { name: 'Search agents' }), 'zzz')
    expect(screen.getByText('No agent matches.')).toBeInTheDocument()
  })

  it('links to the edit screen and the new-agent screen instead of editing in place', async () => {
    agentsApi([bellaco])
    renderAt('/ai/agents')

    expect(await screen.findByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/ai/agents/bellaco/edit')
    expect(screen.getByRole('link', { name: 'Add agent' })).toHaveAttribute('href', '/ai/agents/new')
    expect(screen.queryByRole('textbox', { name: /^Name/ })).not.toBeInTheDocument()
  })

  it('deletes the selected agent after confirmation and returns to the list', async () => {
    const api = agentsApi([bellaco, reporter])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderAt('/ai/agents/reporter')

    await user.click(await screen.findByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(api.calls).toEqual(['DELETE agents/2']))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/ai\/agents$/))
    expect(await screen.findByRole('heading', { name: 'bellaco' })).toBeInTheDocument()
  })

  it('shows the display name instead of the raw name when one is set', async () => {
    const discoverer = agent(4, 'discoverer', { display_name: 'Master Discoverer', role: 'Finds open ports' })
    agentsApi([discoverer, reporter])
    renderAt('/ai/agents')

    const list = within(await screen.findByRole('navigation', { name: 'Agents' }))
    expect(await list.findByText('Master Discoverer')).toBeInTheDocument()
    expect(list.queryByText('discoverer')).not.toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Master Discoverer' })).toBeInTheDocument()
  })

  it('starts an agent with an explicit target and task it never discovered on its own', async () => {
    const api = agentsApi([bellaco, reporter], [{ name: 'bellaco', state: 'stopped' }, { name: 'reporter', state: 'stopped' }])
    const user = userEvent.setup()
    renderAt('/ai/agents/bellaco')

    await user.type(await screen.findByLabelText('Target (optional, comma-separated)'), '10.0.0.77')
    await user.type(screen.getByLabelText('Task (optional)'), 'Check this host for ransomware.')
    await user.click(screen.getByRole('button', { name: 'Start' }))

    await waitFor(() =>
      expect(api.calls).toEqual([
        'POST agents/1/start {"targets":["10.0.0.77"],"message":"Check this host for ransomware."}',
      ]),
    )
  })

  it('says so when the address names no agent', async () => {
    agentsApi([bellaco])
    renderAt('/ai/agents/ghost')

    expect(await screen.findByText('ghost')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to the agents' })).toBeInTheDocument()
  })
})
