import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { BusPage } from './BusPage'

const agent = (id: number, name: string, over: Record<string, unknown> = {}) => ({
  id, name, display_name: null, role: '', system_prompt: '', base_url: '', model_override: '', temperature: 0.2,
  max_iterations: 5, enabled_tools: [], subscribes: [`task.${name}`, `human.${name}`], publishes: [],
  require_approval: 'none', enabled: true, allow_changes: false, ...over,
})

const run = {
  id: 7, started_at: '2026-10-14T10:00:00Z', finished_at: null, status: 'done', targets: [], dry_run: false, model: 'm',
  prompt_tokens: 0, completion_tokens: 0, summary: null, error: null, step_count: 0, services_recorded: 0,
}

function renderPage(path = '/ai/bus') {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <BusPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  queryClient.clear()
  server.use(
    http.get('/api/ai-mode/agents', () =>
      HttpResponse.json([
        agent(1, 'discoverer', { publishes: ['result.#'] }),
        agent(2, 'reporter', { subscribes: ['task.reporter', 'result.discoverer'] }),
      ]),
    ),
    http.get('/api/ai-mode/runs', () => HttpResponse.json([run])),
  )
})

describe('BusPage routing table', () => {
  it('shows who publishes and who listens per topic, and flags topics nobody reads', async () => {
    renderPage()

    const row = (await screen.findByText('result.discoverer')).closest('tr') as HTMLElement
    const cells = within(row).getAllByRole('cell')
    expect(within(cells[1]).getByText('publishes')).toHaveAttribute('title', 'publish pattern result.#')
    expect(within(cells[2]).getByText('listens')).toHaveAttribute('title', 'subscription result.discoverer')
    expect(screen.getByText(/Note: result\.reporter can be published but nobody subscribes/)).toBeInTheDocument()
  })

  it('asks the server who would receive a topic', async () => {
    server.use(
      http.get('/api/ai-mode/bus/route', ({ request }) => {
        const topic = new URL(request.url).searchParams.get('topic')
        return HttpResponse.json({
          topic, valid: true,
          subscribers: [{ agent: 'reporter', enabled: true, pattern: 'result.discoverer' }],
          publishers: [{ agent: 'discoverer', enabled: true, pattern: 'result.#' }],
        })
      }),
    )
    renderPage()

    await userEvent.type(await screen.findByLabelText('Topic to test'), 'result.discoverer')
    expect(await screen.findByText('Would be delivered to')).toBeInTheDocument()
    expect(screen.getByText('via result.discoverer')).toBeInTheDocument()
    expect(screen.getByText('via result.#')).toBeInTheDocument()
  })
})

describe('BusPage topics', () => {
  it('lists traffic per topic and opens the messages of one', async () => {
    const overviewRuns: (string | null)[] = []
    server.use(
      http.get('/api/ai-mode/bus/overview', ({ request }) => {
        overviewRuns.push(new URL(request.url).searchParams.get('run_id'))
        return HttpResponse.json({
          run_id: 7, total_messages: 3,
          topics: [
            { topic: 'result.discoverer', messages: 3, held: 1, last_ts: '2026-10-14T10:05:00Z', publishers: ['discoverer'], recipients: ['reporter'], deliveries: { acked: 2, dropped: 1 } },
          ],
        })
      }),
      http.get('/api/ai-mode/messages', () =>
        HttpResponse.json([
          { id: 1, run_id: 7, ts: '2026-10-14T10:05:00Z', topic: 'result.discoverer', sender: 'discoverer', payload: { text: 'found two hosts' }, correlation_id: 'c', reply_to: null, hops: 1, status: 'delivered', note: null, deliveries: [{ recipient: 'reporter', state: 'acked' }] },
        ]),
      ),
    )
    renderPage('/ai/bus?tab=topics')

    expect(await screen.findByText('3 message(s) on 1 topic(s)')).toBeInTheDocument()
    expect(screen.getByText('2 handled')).toBeInTheDocument()
    expect(screen.getByText('1 dropped')).toBeInTheDocument()
    expect(screen.getByText('1 held')).toBeInTheDocument()
    expect(overviewRuns).toContain('7')

    await userEvent.click(screen.getByText('result.discoverer'))
    expect(await screen.findByText('found two hosts')).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('Include every run'))
    await screen.findByText('3 message(s) on 1 topic(s)')
    expect(overviewRuns).toContain(null)
  })

  it('switches to the topics tab', async () => {
    server.use(http.get('/api/ai-mode/bus/overview', () => HttpResponse.json({ run_id: 7, total_messages: 0, topics: [] })))
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Topics' }))
    expect(await screen.findByText('No messages yet.')).toBeInTheDocument()
  })
})

const message = (id: number, over: Record<string, unknown> = {}) => ({
  id, run_id: 7, ts: `2026-10-14T10:00:0${id}Z`, topic: 'result.discoverer', sender: 'discoverer', payload: { text: `m${id}` },
  correlation_id: 'conv-one-1234', reply_to: null, hops: 0, status: 'delivered', note: null, deliveries: [], ...over,
})

describe('BusPage queues and health', () => {
  it('shows the limits, what waits for a human and what went wrong', async () => {
    server.use(
      http.get('/api/ai-mode/bus/health', () =>
        HttpResponse.json({
          run_id: 7, active: true, approval_timeout_seconds: 600,
          messages: { used: 45, limit: 50 }, hops: { used: 3, limit: 8 }, seconds: { used: 90, limit: 600 },
          agents: [{ name: 'reviewer', queued: 2, working: true, held: 1, dropped: 0 }],
          held: [{ message_id: 4, topic: 'result.reviewer', sender: 'reviewer', ts: '2026-10-14T10:00:00Z', age_seconds: 700, overdue: true }],
          problems: [{ kind: 'rejected', message_id: 5, topic: 'result.bellaco', sender: 'bellaco', recipient: null, reason: 'too broad', ts: '2026-10-14T10:00:00Z' }],
        }),
      ),
    )
    renderPage('/ai/bus?tab=health')

    expect(await screen.findByRole('progressbar', { name: 'Messages' })).toHaveAttribute('aria-valuenow', '90')
    expect(screen.getByRole('progressbar', { name: 'Time' })).toHaveAttribute('aria-valuenow', '15')
    expect(screen.getByText(/past the 10m 0s limit: treated as rejected/)).toBeInTheDocument()
    expect(screen.getByText(/too broad/)).toBeInTheDocument()
    const row = screen.getByText('reviewer', { selector: 'td' }).closest('tr') as HTMLElement
    expect(within(row).getAllByRole('cell').map((c) => c.textContent)).toEqual(['reviewer', 'yes', '2', '1', '0'])
  })
})

describe('BusPage live flow and conversations', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/ai-mode/messages', () =>
        HttpResponse.json([
          message(1, { topic: 'task.discoverer', sender: 'human', deliveries: [{ recipient: 'discoverer', state: 'acked' }] }),
          message(2, { hops: 1, deliveries: [{ recipient: 'reporter', state: 'dropped' }] }),
          message(3, { correlation_id: 'conv-two-5678', status: 'held', payload: { text: 'held one' } }),
        ]),
      ),
    )
  })

  it('draws a dot per message, filters by conversation and opens a message', async () => {
    renderPage('/ai/bus?tab=flow')

    const svg = await screen.findByRole('img', { name: 'Message flow between agents' })
    await waitFor(() => expect(svg.querySelectorAll('circle')).toHaveLength(3))
    expect(svg.querySelectorAll('line[marker-end]')).toHaveLength(2)

    await userEvent.selectOptions(screen.getByLabelText('Conversation'), 'conv-two-5678')
    await waitFor(() => expect(svg.querySelectorAll('circle')).toHaveLength(1))

    await userEvent.click(svg.querySelector('circle') as Element)
    expect(await screen.findByText(/held until a human approves/)).toBeInTheDocument()
  })

  it('lists each conversation with messages indented by hop', async () => {
    renderPage('/ai/bus?tab=conversations')

    expect(await screen.findByText(/2 message\(s\), human, discoverer, reporter/)).toBeInTheDocument()
    const reply = screen.getByText('m2').closest('li') as HTMLElement
    expect(reply).toHaveStyle({ paddingLeft: '20px' })
    expect(screen.getByText('1 held')).toBeInTheDocument()
  })
})
