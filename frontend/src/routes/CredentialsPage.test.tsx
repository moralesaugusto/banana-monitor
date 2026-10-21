import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Credential } from '../api/credentials'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { CredentialsPage } from './CredentialsPage'

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <CredentialsPage />
    </QueryClientProvider>,
  )
}

const CREDENTIALS: Credential[] = [
  {
    id: 1,
    label: 'pve1-token',
    credential_type: 'api_token',
    created_at: '2026-01-01T00:00:00Z',
    rotated_at: null,
    last_used_at: '2026-01-02T00:00:00Z',
  },
]

describe('CredentialsPage', () => {
  beforeEach(() => {
    queryClient.clear()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('lists credentials and deletes one', async () => {
    let deleted = false
    server.use(
      http.get('/api/credentials', () => HttpResponse.json(deleted ? [] : CREDENTIALS)),
      http.delete('/api/credentials/1', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('pve1-token')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Delete/ }))

    await waitFor(() => expect(screen.queryByText('pve1-token')).not.toBeInTheDocument())
    expect(screen.getByText('No credentials saved yet.')).toBeInTheDocument()
  })

  it('shows the backend\'s specific reason when a credential is still in use', async () => {
    server.use(
      http.get('/api/credentials', () => HttpResponse.json(CREDENTIALS)),
      http.delete('/api/credentials/1', () =>
        HttpResponse.json(
          { detail: 'Credential is still used by integration pve1. Change or remove those first.' },
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('pve1-token')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Delete/ }))

    expect(
      await screen.findByText('Credential is still used by integration pve1. Change or remove those first.'),
    ).toBeInTheDocument()
    expect(screen.getByText('pve1-token')).toBeInTheDocument()
  })
})
