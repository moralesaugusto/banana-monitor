import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
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
})
