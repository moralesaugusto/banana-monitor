import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { AiRunSummary } from '../../api/aiMode'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { AiRunsPage } from './AiRunsPage'

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AiRunsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const FAILED_RUN: AiRunSummary = {
  id: 11,
  started_at: '2026-10-13T20:48:17Z',
  finished_at: '2026-10-13T20:50:25Z',
  status: 'error',
  targets: ['10.0.0.55'],
  dry_run: false,
  model: 'llama3.2:latest',
  prompt_tokens: 72183,
  completion_tokens: 656,
  summary: 'Stopped at the iteration limit.',
  error: 'reporter: ReadTimeout (no response within 120s)',
  step_count: 45,
  services_recorded: 0,
  entry_agent: 'bellaco',
}

describe('AiRunsPage', () => {
  beforeEach(() => queryClient.clear())

  it('shows the failure reason, entry agent and duration inline, without opening the run', async () => {
    server.use(http.get('/api/ai-mode/runs', () => HttpResponse.json([FAILED_RUN])))
    renderPage()

    expect(await screen.findByText('reporter: ReadTimeout (no response within 120s)')).toBeInTheDocument()
    expect(screen.getByText('bellaco')).toBeInTheDocument()
    expect(screen.getByText('2m 08s')).toBeInTheDocument()
    expect(screen.getByText('error')).toHaveClass('text-red-600')
  })

  it('falls back to the final summary when there is no error, and to a dash for a bare entry agent', async () => {
    const done: AiRunSummary = {
      ...FAILED_RUN,
      id: 12,
      status: 'done',
      error: null,
      summary: 'Discovered 3 services.',
      entry_agent: '',
      finished_at: null,
    }
    server.use(http.get('/api/ai-mode/runs', () => HttpResponse.json([done])))
    renderPage()

    expect(await screen.findByText('Discovered 3 services.')).toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})

describe('AiRunsPage filters', () => {
  beforeEach(() => queryClient.clear())
  const runs: AiRunSummary[] = [
    { ...FAILED_RUN, id: 1, model: 'alpha', agents: ['bellaco'], tools: ['run_nmap'], entry_agent: 'bellaco' },
    { ...FAILED_RUN, id: 2, model: 'beta', status: 'done', error: null, summary: 'ok', agents: ['reporter'], tools: ['run_nc'], entry_agent: 'reporter' },
  ]

  it('filters from the right-hand panel, shows removable chips, and clears', async () => {
    server.use(http.get('/api/ai-mode/runs', () => HttpResponse.json(runs)))
    renderPage()
    expect(await screen.findByText('#1')).toBeInTheDocument()
    expect(screen.getByText('#2')).toBeInTheDocument()

    await userEvent.click(within(screen.getByRole('region', { name: 'Tools' })).getByLabelText(/run_nc/))
    expect(screen.queryByText('#1')).not.toBeInTheDocument()
    expect(screen.getByText('#2')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Remove tool filter run_nc' }))
    expect(screen.getByText('#1')).toBeInTheDocument()
  })

  it('applies a filter when a model cell is clicked, and the Errors tab narrows to failures', async () => {
    server.use(http.get('/api/ai-mode/runs', () => HttpResponse.json(runs)))
    renderPage()
    await screen.findByText('#1')

    await userEvent.click(screen.getByTitle('Filter by model beta'))
    expect(screen.queryByText('#1')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Clear all' }))
    await userEvent.click(screen.getByRole('button', { name: /^Errors/ }))
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.queryByText('#2')).not.toBeInTheDocument()
  })
})
