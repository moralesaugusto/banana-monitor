import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { SshHostKeysCard } from './SshHostKeysCard'

describe('SshHostKeysCard', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('lists keys awaiting approval and approves one', async () => {
    let approved = false
    server.use(
      http.get('/api/ssh-host-keys', () =>
        HttpResponse.json([
          { id: 4, host: '10.0.0.7', port: 22, fingerprint: 'SHA256:abc', approved, changed: false, first_seen_at: '2026-10-09T00:00:00Z' },
        ]),
      ),
      http.post('/api/ssh-host-keys/4/approve', () => {
        approved = true
        return HttpResponse.json({})
      }),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <SshHostKeysCard />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('10.0.0.7:22')).toBeInTheDocument()
    expect(screen.getByText('needs approval')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(approved).toBe(true))
    expect(await screen.findByText('approved')).toBeInTheDocument()
  })

  it('shows nothing when no host key has been seen', async () => {
    server.use(http.get('/api/ssh-host-keys', () => HttpResponse.json([])))
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <SshHostKeysCard />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })
})
