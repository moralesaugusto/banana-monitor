import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { AiLearnPage } from './AiLearnPage'

function renderPage() {
  server.use(
    http.get('/api/ai-mode/runs', () => HttpResponse.json([])),
    http.get('/api/ai-mode/agents', () => HttpResponse.json([])),
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AiLearnPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AiLearnPage tools and guardrails', () => {
  beforeEach(() => queryClient.clear())

  it('teaches the steps a call meets and replays the latest real stopped call', async () => {
    server.use(
      http.get('/api/ai-mode/tools/usage', () =>
        HttpResponse.json([
          { name: 'run_nc', calls: 1, errors: 1, last_used: '2026-11-13T10:00:00Z', last_run_id: 4, worked_request: null,
            worked_response: null, worked_run_id: null, stopped_request: { target: '1.1.1.1' },
            stopped_reason: '1.1.1.1 is not inside any configured network', stopped_run_id: 4 },
          { name: 'run_nmap', calls: 2, errors: 1, last_used: '2026-11-13T11:00:00Z', last_run_id: 9, worked_request: null,
            worked_response: null, worked_run_id: null, stopped_request: { target: '8.8.8.8' },
            stopped_reason: 'flag not allowed', stopped_run_id: 9 },
        ]),
      ),
    )
    renderPage()

    expect(await screen.findByText('Part 4: tools and guardrails')).toBeInTheDocument()
    expect(screen.getByText(/Do the tool's own checks pass\?/)).toBeInTheDocument()
    expect(await screen.findByText('flag not allowed')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'run #9' })).toHaveAttribute('href', '/ai/runs/9')
    expect(screen.queryByText('1.1.1.1 is not inside any configured network')).not.toBeInTheDocument()
  })

  it('says so when nothing has been stopped yet', async () => {
    server.use(http.get('/api/ai-mode/tools/usage', () => HttpResponse.json([])))
    renderPage()
    expect(await screen.findByText(/No call has been stopped yet/)).toBeInTheDocument()
  })
})
