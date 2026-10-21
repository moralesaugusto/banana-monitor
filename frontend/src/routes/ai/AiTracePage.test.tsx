import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { AiTracePage } from './AiTracePage'

describe('AiTracePage', () => {
  beforeEach(() => queryClient.clear())

  it('explains each step in plain English', async () => {
    server.use(
      http.get('/api/ai-mode/runs/3', () =>
        HttpResponse.json({
          id: 3, started_at: '2026-10-08T00:00:00Z', finished_at: '2026-10-08T00:00:20Z', status: 'done',
          targets: ['192.168.1.5'], dry_run: false, model: 'qwen', prompt_tokens: 300, completion_tokens: 40,
          summary: 'Found SSH.', error: null, step_count: 3, services_recorded: 1, base_url: 'http://x/v1',
          system_prompt: 'You are an agent', settings_snapshot: {},
          steps: [
            { idx: 0, ts: '2026-10-08T00:00:01Z', kind: 'llm', name: 'qwen', request: [], duration_ms: 900,
              prompt_tokens: 200, completion_tokens: 20,
              response: { content: null, reasoning: 'scan first', tool_calls: [{ name: 'run_nmap', arguments: '{"target":"192.168.1.5"}' }] } },
            { idx: 1, ts: '2026-10-08T00:00:02Z', kind: 'tool', name: 'run_nmap', request: { target: '192.168.1.5', flags: ['-sV'] },
              response: { exit_code: 0, output: '22/tcp open ssh' }, duration_ms: 4000, prompt_tokens: 0, completion_tokens: 0 },
            { idx: 2, ts: '2026-10-08T00:00:03Z', kind: 'tool', name: 'record_service',
              request: { ip: '192.168.1.5', port: 22, service_type: 'tcp' }, response: { recorded: true }, duration_ms: 10,
              prompt_tokens: 0, completion_tokens: 0 },
            { idx: 3, ts: '2026-10-08T00:00:04Z', kind: 'tool', name: 'report_open_ports',
              request: { ip: '192.168.1.5', ports: [22, 80] }, response: { reported: true }, duration_ms: 5,
              prompt_tokens: 0, completion_tokens: 0 },
          ],
        }),
      ),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/ai/runs/3']}>
          <Routes>
            <Route path="/ai/runs/:id" element={<AiTracePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText(/decided to use a tool: run_nmap/)).toBeInTheDocument()
    expect(screen.getByText(/Ran nmap on 192.168.1.5/)).toBeInTheDocument()
    expect(screen.getByText(/Recorded 192.168.1.5:22 as tcp/)).toBeInTheDocument()
    expect(screen.getByText(/Reported 192.168.1.5's open ports \(22, 80\)/)).toBeInTheDocument()
    expect(screen.getByText('Found SSH.')).toBeInTheDocument()
  })

  it('flags an agent that keeps failing the same tool call in a row', async () => {
    const failedCall = (idx: number) => ({
      idx, ts: '2026-10-08T00:00:01Z', kind: 'tool', name: 'run_nc', agent: 'reviewer',
      request: { target: '192.168.1.5', port: 443 }, response: { error: 'empty' }, duration_ms: 10,
      prompt_tokens: 0, completion_tokens: 0,
    })
    server.use(
      http.get('/api/ai-mode/runs/4', () =>
        HttpResponse.json({
          id: 4, started_at: '2026-10-08T00:00:00Z', finished_at: '2026-10-08T00:00:20Z', status: 'done',
          targets: ['192.168.1.5'], dry_run: false, model: 'qwen', prompt_tokens: 0, completion_tokens: 0,
          summary: null, error: null, step_count: 3, services_recorded: 0, base_url: 'http://x/v1',
          system_prompt: 'You are an agent', settings_snapshot: {},
          steps: [failedCall(0), failedCall(1), failedCall(2)],
        }),
      ),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/ai/runs/4']}>
          <Routes>
            <Route path="/ai/runs/:id" element={<AiTracePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText(/3 failed run_nc calls in a row/)).toBeInTheDocument()
  })
})
