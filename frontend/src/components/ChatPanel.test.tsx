import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { AssistantMessage } from '../api/assistant'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { ChatPanel } from './ChatPanel'

function renderPanel() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ChatPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ChatPanel', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('opens, sends a message, and shows the reply with a tool-call chip', async () => {
    const messages: AssistantMessage[] = []
    server.use(
      http.get('/api/assistant/messages', () => HttpResponse.json(messages)),
      http.post('/api/assistant/chat', async ({ request }) => {
        const body = (await request.json()) as { message: string }
        const reply: AssistantMessage = {
          id: 1,
          ts: new Date().toISOString(),
          role: 'assistant',
          content: 'You have **1** device.',
          tool_calls: [{ name: 'list_devices', arguments: {}, result: [{ id: 1 }] }],
        }
        messages.push(
          { id: 0, ts: new Date().toISOString(), role: 'user', content: body.message, tool_calls: null },
          reply,
        )
        return HttpResponse.json({ reply })
      }),
    )

    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByTitle('Open assistant'))
    expect(await screen.findByText(/Ask about your devices/)).toBeInTheDocument()

    const input = screen.getByPlaceholderText('Ask the assistant…')
    await user.type(input, 'how many devices do I have?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText(/You have/)).toBeInTheDocument()
    expect(screen.getByText(/list_devices/)).toBeInTheDocument()
  })

  it('clears the conversation', async () => {
    const initialMessages: AssistantMessage[] = [
      { id: 1, ts: new Date().toISOString(), role: 'user', content: 'hello', tool_calls: null },
    ]
    server.use(
      http.get('/api/assistant/messages', () => HttpResponse.json(initialMessages)),
      http.delete('/api/assistant/messages', () => new HttpResponse(null, { status: 204 })),
    )

    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByTitle('Open assistant'))
    expect(await screen.findByText('hello')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Clear conversation' }))

    await waitFor(() => expect(screen.queryByText('hello')).not.toBeInTheDocument())
  })

  it('links the settings gear to the Assistant tab under AI Mode settings', async () => {
    server.use(http.get('/api/assistant/messages', () => HttpResponse.json([])))
    const user = userEvent.setup()
    renderPanel()
    await user.click(screen.getByTitle('Open assistant'))

    const gear = screen.getByTitle('Assistant settings')
    expect(gear).toHaveAttribute('href', '/ai/config?tab=assistant')
  })
})
