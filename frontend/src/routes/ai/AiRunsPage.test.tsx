import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
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
  targets: ['192.168.1.55'],
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
