import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { AiRunPage } from './AiRunPage'

const run = {
  id: 4, started_at: '2026-10-14T10:00:00Z', finished_at: '2026-10-14T10:01:00Z', status: 'done', targets: ['10.0.0.1'],
  dry_run: false, model: 'm', prompt_tokens: 10, completion_tokens: 5, summary: 'All good', error: null, step_count: 2,
  services_recorded: 1, started_by: 'schedule', entry_agent: 'discoverer',
}

describe('AiRunPage log', () => {
  beforeEach(() => queryClient.clear())

  it('merges bus messages and agent steps in time order and filters them', async () => {
    server.use(
      http.get('/api/ai-mode/settings', () => HttpResponse.json({ enabled: true })),
      http.get('/api/ai-mode/agents', () => HttpResponse.json([])),
      http.get('/api/ai-mode/runs', () => HttpResponse.json([run])),
      http.get('/api/ai-mode/runs/4', () =>
        HttpResponse.json({
          ...run, base_url: '', system_prompt: '', settings_snapshot: { entry_agent: 'discoverer' },
          steps: [
            { idx: 0, ts: '2026-10-14T10:00:02Z', kind: 'tool', name: 'run_nmap', agent: 'discoverer', request: { target: '10.0.0.1' }, response: { ok: true }, duration_ms: 90, prompt_tokens: 0, completion_tokens: 0 },
            { idx: 1, ts: '2026-10-14T10:00:05Z', kind: 'llm', name: 'm', agent: 'reviewer', request: {}, response: { content: 'looks fine', tool_calls: [] }, duration_ms: 400, prompt_tokens: 3, completion_tokens: 2 },
          ],
        }),
      ),
      http.get('/api/ai-mode/messages', () =>
        HttpResponse.json([
          { id: 1, run_id: 4, ts: '2026-10-14T10:00:01Z', topic: 'task.discoverer', sender: 'human', payload: { text: 'Go scan' }, correlation_id: 'c', reply_to: null, hops: 0, status: 'delivered', note: null, deliveries: [{ recipient: 'discoverer', state: 'acked' }] },
        ]),
      ),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AiRunPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('3 of 3 entries')).toBeInTheDocument()
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('task.discoverer'),
      expect.stringContaining('run_nmap'),
      expect.stringContaining('looks fine'),
    ])

    await userEvent.selectOptions(screen.getByLabelText('Agent'), 'reviewer')
    expect(screen.getByText('1 of 3 entries')).toBeInTheDocument()
    await userEvent.click(screen.getByText('looks fine'))
    expect(screen.getByText(/The model decided it was done/)).toBeInTheDocument()
  })
})
