import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { CustomToolsEditor } from './CustomToolsEditor'

describe('CustomToolsEditor', () => {
  beforeEach(() => queryClient.clear())

  it('lists tools and posts a new command tool', async () => {
    const tools = [
      { id: 1, name: 'whatweb_scan', description: 'web id', kind: 'command', command: ['whatweb', '{target}'],
        mcp_url: null, mcp_tool: null, parameters: {}, enabled: true },
    ]
    let posted: Record<string, unknown> | null = null
    server.use(
      http.get('/api/ai-mode/custom-tools', () => HttpResponse.json(tools)),
      http.post('/api/ai-mode/custom-tools', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 2, ...posted }, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={queryClient}>
        <CustomToolsEditor />
      </QueryClientProvider>,
    )

    expect(await screen.findByText('whatweb_scan')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add tool' }))
    await user.type(screen.getByPlaceholderText('whatweb_scan'), 'banner_probe')
    await user.type(screen.getByPlaceholderText('whatweb --no-errors {target}'), 'nc -n {{target} {{port}')
    await user.click(screen.getByRole('button', { name: 'Add tool' }))

    await screen.findByText('whatweb_scan')
    expect(posted).toMatchObject({ name: 'banner_probe', kind: 'command', command: ['nc', '-n', '{target}', '{port}'] })
  })

  it('tests one tool on its own row, and tests all tools at once', async () => {
    const tools = [
      { id: 1, name: 'good_tool', description: 'd', kind: 'command', command: ['nmap', '{target}'],
        mcp_url: null, mcp_tool: null, parameters: {}, enabled: true },
      { id: 2, name: 'broken_tool', description: 'd', kind: 'command', command: ['nc', '{target}'],
        mcp_url: null, mcp_tool: null, parameters: {}, enabled: true },
    ]
    server.use(
      http.get('/api/ai-mode/custom-tools', () => HttpResponse.json(tools)),
      http.post('/api/ai-mode/custom-tools/1/test', () =>
        HttpResponse.json({
          id: 1, name: 'good_tool', ok: true, detail: 'Called successfully.', duration_ms: 42,
          arguments_used: { target: '127.0.0.1' },
        }),
      ),
      http.post('/api/ai-mode/custom-tools/test-all', () =>
        HttpResponse.json([
          { id: 1, name: 'good_tool', ok: true, detail: 'Called successfully.', duration_ms: 42,
            arguments_used: { target: '127.0.0.1' } },
          { id: 2, name: 'broken_tool', ok: false, detail: 'nc is not installed', duration_ms: 5,
            arguments_used: { target: '127.0.0.1' } },
        ]),
      ),
    )
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={queryClient}>
        <CustomToolsEditor />
      </QueryClientProvider>,
    )
    await screen.findByText('good_tool')

    const row = screen.getByText('good_tool').closest('li')
    expect(row).not.toBeNull()
    await user.click(within(row as HTMLElement).getByRole('button', { name: 'Test' }))
    expect(await screen.findByText(/Called successfully in 42 ms/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Test all tools' }))
    expect(await screen.findByText('1 of 2 tool(s) failed: broken_tool.')).toBeInTheDocument()
    expect(screen.getByText(/Failed in 5 ms: nc is not installed/)).toBeInTheDocument()
  })
})
