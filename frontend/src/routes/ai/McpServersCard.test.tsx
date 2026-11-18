import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { AiToolsPage } from './AiToolsPage'
import { McpServersCard } from './McpServersCard'

const URL = 'http://hex.local:8891/mcp'
const hexstrike = { id: 1, name: 'HexStrike', url: URL, tool_count: 2 }

function renderCard() {
  render(
    <QueryClientProvider client={queryClient}>
      <McpServersCard />
    </QueryClientProvider>,
  )
}

describe('McpServersCard', () => {
  beforeEach(() => queryClient.clear())

  it('tests an address before saving it, and shows what the server offers', async () => {
    server.use(
      http.get('/api/ai-mode/mcp-servers', () => HttpResponse.json([])),
      http.post('/api/ai-mode/mcp-servers/test', () =>
        HttpResponse.json({
          ok: true, detail: '', server_name: 'hexstrike', server_version: '6.0',
          tool_count: 2, tool_names: ['nmap_scan', 'execute_command'], duration_ms: 12,
        }),
      ),
    )
    const user = userEvent.setup()
    renderCard()

    await user.type(await screen.findByPlaceholderText('http://10.0.0.10:8891/mcp'), URL)
    await user.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(await screen.findByText(/Connected to hexstrike 6.0 in 12 ms. It offers 2 tool\(s\)/)).toBeInTheDocument()
    expect(screen.getByText('nmap_scan, execute_command')).toBeInTheDocument()
  })

  it('lists a server\'s tools under it, expanded on demand', async () => {
    const tool = (id: number, name: string, serverId: number | null) => ({
      id, name, description: `${name} desc`, kind: 'mcp', command: [], mcp_url: URL, mcp_tool: name,
      parameters: {}, enabled: true, mcp_server_id: serverId,
    })
    server.use(
      http.get('/api/ai-mode/mcp-servers', () => HttpResponse.json([hexstrike])),
      http.get('/api/ai-mode/custom-tools', () =>
        HttpResponse.json([tool(1, 'nmap_scan', 1), tool(2, 'other_tool', 99)]),
      ),
    )
    const user = userEvent.setup()
    renderCard()

    expect(screen.queryByText('nmap_scan')).not.toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: /Show 2 imported tool/ }))
    expect(screen.getByText('nmap_scan')).toBeInTheDocument()
    expect(screen.queryByText('other_tool')).not.toBeInTheDocument()
  })

  it('reports a failed connection', async () => {
    server.use(
      http.get('/api/ai-mode/mcp-servers', () => HttpResponse.json([])),
      http.post('/api/ai-mode/mcp-servers/test', () =>
        HttpResponse.json({ ok: false, detail: 'MCP server did not answer (ConnectError)', server_name: '',
          server_version: '', tool_count: 0, tool_names: [], duration_ms: 3 }),
      ),
    )
    const user = userEvent.setup()
    renderCard()
    await user.type(await screen.findByPlaceholderText('http://10.0.0.10:8891/mcp'), URL)
    await user.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/Connection failed: MCP server did not answer/)).toBeInTheDocument()
  })

  it('adds a server and imports its tools in one step, warning about tools no network check can cover', async () => {
    let created: unknown
    let imported = false
    server.use(
      http.get('/api/ai-mode/mcp-servers', () => HttpResponse.json([])),
      http.post('/api/ai-mode/mcp-servers', async ({ request }) => {
        created = await request.json()
        return HttpResponse.json(hexstrike, { status: 201 })
      }),
      http.post('/api/ai-mode/mcp-servers/1/import', () => {
        imported = true
        return HttpResponse.json({ added: 2, updated: 0, removed: 0, unscoped: ['execute_command'] })
      }),
    )
    const user = userEvent.setup()
    renderCard()

    await user.type(await screen.findByPlaceholderText('HexStrike'), 'HexStrike')
    await user.type(screen.getByPlaceholderText('http://10.0.0.10:8891/mcp'), URL)
    await user.click(screen.getByRole('button', { name: 'Add and import tools' }))

    expect(await screen.findByText('Imported: 2 added, 0 updated, 0 removed.')).toBeInTheDocument()
    expect(created).toEqual({ name: 'HexStrike', url: URL })
    expect(imported).toBe(true)
    expect(screen.getByText(/execute_command/)).toBeInTheDocument()
  })

  it('refreshes a server, optionally removing tools it dropped', async () => {
    let body: unknown
    server.use(
      http.get('/api/ai-mode/mcp-servers', () => HttpResponse.json([hexstrike])),
      http.post('/api/ai-mode/mcp-servers/1/import', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ added: 0, updated: 1, removed: 1, unscoped: [] })
      }),
    )
    const user = userEvent.setup()
    renderCard()

    await user.click(await screen.findByLabelText('Remove tools it no longer offers'))
    await user.click(screen.getByRole('button', { name: 'Refresh tools' }))

    expect(await screen.findByText('Imported: 0 added, 1 updated, 1 removed.')).toBeInTheDocument()
    expect(body).toEqual({ remove_missing: true })
  })

  it('deletes the server and its tools only after confirming', async () => {
    let deleted = false
    server.use(
      http.get('/api/ai-mode/mcp-servers', () => HttpResponse.json([hexstrike])),
      http.delete('/api/ai-mode/mcp-servers/1', () => {
        deleted = true
        return HttpResponse.json({ tools_removed: 2 })
      }),
    )
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    const user = userEvent.setup()
    renderCard()

    const button = await screen.findByRole('button', { name: 'Delete server and tools' })
    await user.click(button)
    expect(deleted).toBe(false)
    await user.click(button)
    await waitFor(() => expect(deleted).toBe(true))
    expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('its 2 imported tool(s)'))
  })

  it('edits a server address', async () => {
    let body: unknown
    server.use(
      http.get('/api/ai-mode/mcp-servers', () => HttpResponse.json([hexstrike])),
      http.put('/api/ai-mode/mcp-servers/1', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(hexstrike)
      }),
    )
    const user = userEvent.setup()
    renderCard()

    await user.click(await screen.findByRole('button', { name: 'Edit' }))
    const address = screen.getByLabelText('Edit server address')
    await user.clear(address)
    await user.type(address, 'http://new-host:9000/mcp')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(body).toEqual({ name: 'HexStrike', url: 'http://new-host:9000/mcp' }))
  })
})

describe('AiToolsPage tabs', () => {
  beforeEach(() => queryClient.clear())

  it('keeps MCP servers and tools on the Tools tab and the guardrails on their own tab', async () => {
    server.use(
      http.get('/api/ai-mode/tools', () =>
        HttpResponse.json({ default_system_prompt: '', guardrails: ['Single IP only'], allowed_nmap_flags: '', tools: [] }),
      ),
      http.get('/api/ai-mode/custom-tools', () => HttpResponse.json([])),
      http.get('/api/ai-mode/guardrails', () => HttpResponse.json([])),
      http.get('/api/ai-mode/mcp-servers', () => HttpResponse.json([])),
      http.get('/api/ai-mode/tools/usage', () => HttpResponse.json([])),
      http.get('/api/ai-mode/agents', () => HttpResponse.json([])),
      http.get('/api/ai-mode/tools/availability', () => HttpResponse.json([])),
    )
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AiToolsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('MCP servers')).toBeInTheDocument()
    expect(screen.queryByText('Single IP only')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Guardrails' }))
    expect(await screen.findByText('Single IP only')).toBeInTheDocument()
    expect(screen.queryByText('MCP servers')).not.toBeInTheDocument()
  })
})
