import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { MessagesPage } from './MessagesPage'

const run = {
  id: 7, started_at: '2026-10-09T10:00:00Z', finished_at: null, status: 'running', targets: [], dry_run: false,
  model: 'm', prompt_tokens: 0, completion_tokens: 0, summary: null, error: null, step_count: 0,
  services_recorded: 0, paused: false,
}
const message = (over: Record<string, unknown>) => ({
  id: 1, run_id: 7, ts: '2026-10-09T10:00:01Z', topic: 'task.discoverer', sender: 'human',
  payload: { text: 'scan it' }, correlation_id: 'abc', reply_to: null, hops: 0, status: 'delivered',
  note: null, deliveries: [{ recipient: 'discoverer', state: 'acked' }], ...over,
})

describe('MessagesPage', () => {
  beforeEach(() => queryClient.clear())

  it('shows the log with delivery states and lets a human approve an edited held message', async () => {
    let approved: unknown = null
    server.use(
      http.get('/api/ai-mode/runs', () => HttpResponse.json([run])),
      http.get('/api/ai-mode/messages', () =>
        HttpResponse.json([
          message({}),
          message({ id: 2, topic: 'result.discoverer', sender: 'discoverer', status: 'held', payload: { text: 'draft' }, deliveries: [{ recipient: 'reviewer', state: 'pending' }] }),
        ]),
      ),
      http.post('/api/ai-mode/messages/2/approve', async ({ request }) => {
        approved = await request.json()
        return HttpResponse.json({ status: 'approved' }, { status: 202 })
      }),
    )
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={queryClient}>
        <MessagesPage />
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Waiting for you (1)')).toBeInTheDocument()
    expect(screen.getByText('discoverer acked')).toBeInTheDocument()

    const box = screen.getByLabelText('Edit before approving')
    await user.clear(box)
    await user.type(box, 'better')
    await user.click(screen.getByRole('button', { name: 'Approve edited' }))

    await waitFor(() => expect(approved).toEqual({ payload: { text: 'better' } }))
  })
})
