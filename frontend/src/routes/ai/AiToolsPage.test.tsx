import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { AiToolsPage } from './AiToolsPage'

const TOOLS = {
  default_system_prompt: '',
  guardrails: [],
  allowed_nmap_flags: '',
  tools: [
    {
      name: 'run_nmap', description: 'scan', enabled: true,
      parameters: { type: 'object', properties: { target: { type: 'string' } }, required: ['target'] },
      runs_on: 'local_program', runs_on_label: 'A program on the Banana host', where: 'Runs nmap with no shell.',
      safeguards: ['Flags must match a fixed allowlist.'], agents: [{ id: 1, name: 'discoverer' }],
    },
    {
      name: 'run_nc', description: 'connect', parameters: {}, enabled: true,
      runs_on: 'local_program', runs_on_label: 'A program on the Banana host', where: 'Runs nc once.',
      safeguards: ['The port must be 1 to 65535.'], agents: [],
    },
  ],
}

const USAGE = [
  {
    name: 'run_nmap', calls: 3, errors: 1, last_used: '2026-11-13T10:00:00Z', last_run_id: 7,
    worked_request: { target: '10.0.0.6' }, worked_response: { exit_code: 0 }, worked_run_id: 7,
    stopped_request: { target: '8.8.8.8' }, stopped_reason: '8.8.8.8 is not inside any configured network', stopped_run_id: 6,
  },
]

describe('AiToolsPage availability', () => {
  beforeEach(() => queryClient.clear())

  it('checks only on request, then flags each tool and lists the ones that cannot run', async () => {
    let checks = 0
    server.use(
      http.get('/api/ai-mode/tools', () => HttpResponse.json(TOOLS)),
      http.get('/api/ai-mode/custom-tools', () => HttpResponse.json([])),
      http.get('/api/ai-mode/guardrails', () => HttpResponse.json([])),
      http.get('/api/ai-mode/tools/usage', () => HttpResponse.json(USAGE)),
      http.get('/api/ai-mode/agents', () => HttpResponse.json([])),
      http.get('/api/ai-mode/tools/availability', () => {
        checks += 1
        return HttpResponse.json([
          { name: 'run_nmap', kind: 'builtin', status: 'ok', detail: 'nmap found' },
          { name: 'run_nc', kind: 'builtin', status: 'missing', detail: 'nc is not on PATH' },
        ])
      }),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AiToolsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const button = await screen.findByRole('button', { name: 'Check availability' })
    expect(checks).toBe(0)

    await userEvent.click(button)

    expect(await screen.findByText('1 of 2 tools available')).toBeInTheDocument()
    expect(screen.getByText('nc is not on PATH')).toBeInTheDocument()
    expect(screen.getByText('available')).toBeInTheDocument()
    expect(checks).toBe(1)
  })

  it('explains where each tool runs, what limits it, who has it and how it has been used', async () => {
    server.use(
      http.get('/api/ai-mode/tools', () => HttpResponse.json(TOOLS)),
      http.get('/api/ai-mode/custom-tools', () => HttpResponse.json([])),
      http.get('/api/ai-mode/guardrails', () => HttpResponse.json([])),
      http.get('/api/ai-mode/tools/usage', () => HttpResponse.json(USAGE)),
      http.get('/api/ai-mode/agents', () => HttpResponse.json([])),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AiToolsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Runs nmap with no shell.')).toBeInTheDocument()
    expect(screen.getByText('Flags must match a fixed allowlist.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'discoverer' })).toHaveAttribute('href', '/ai/agents/discoverer')
    expect(screen.getByText(/Called 3 times; 1 refused or failed/)).toBeInTheDocument()
    expect(screen.getByText('Never called yet.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /a call that was stopped \(run #6\)/ }))
    expect(screen.getByText(/Stopped: 8.8.8.8 is not inside any configured network/)).toBeInTheDocument()
  })

  it('checks a hand-written call and shows which step stops it, without running anything', async () => {
    let sent: unknown
    server.use(
      http.get('/api/ai-mode/tools', () => HttpResponse.json(TOOLS)),
      http.get('/api/ai-mode/custom-tools', () => HttpResponse.json([])),
      http.get('/api/ai-mode/guardrails', () => HttpResponse.json([])),
      http.get('/api/ai-mode/tools/usage', () => HttpResponse.json([])),
      http.get('/api/ai-mode/agents', () => HttpResponse.json([{ id: 1, name: 'discoverer' }])),
      http.post('/api/ai-mode/tools/run_nmap/try', async ({ request }) => {
        sent = await request.json()
        return HttpResponse.json({
          would_run: false,
          command: null,
          stages: [
            { id: 'enabled', title: 'Is it enabled for this agent?', status: 'pass', detail: 'discoverer has it enabled.' },
            { id: 'checks', title: "Do the tool's own checks accept the arguments?", status: 'stop', detail: 'flag not allowed' },
            { id: 'result', title: 'What would happen?', status: 'skip', detail: 'Not reached: an earlier step stopped the call.' },
          ],
        })
      }),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AiToolsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await screen.findByText('Runs nmap with no shell.')
    await userEvent.click(screen.getAllByRole('button', { name: 'Try a call' })[0])
    await userEvent.selectOptions(screen.getByLabelText('As agent'), 'discoverer')
    await userEvent.click(screen.getByRole('button', { name: 'Check this call' }))

    expect(await screen.findByText('Stopped here')).toBeInTheDocument()
    expect(screen.getByText('flag not allowed')).toBeInTheDocument()
    expect(screen.getByText('This call would be stopped.')).toBeInTheDocument()
    expect(sent).toEqual({ arguments: { target: '127.0.0.1' }, agent_id: 1 })
  })
})
