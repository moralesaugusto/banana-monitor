import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Credential } from '../api/credentials'
import type { Network } from '../api/types'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { NetworksPage } from './NetworksPage'

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NetworksPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const NETWORKS: Network[] = [
  { id: 1, site_id: 1, name: 'LAN', cidr: '192.168.1.0/24', vlan_id: null, description: null },
]

const CREDENTIALS: Credential[] = [
  { id: 5, label: 'homelab-ssh', credential_type: 'ssh_key', created_at: '', rotated_at: null, last_used_at: null },
]

describe('NetworksPage', () => {
  beforeEach(() => {
    queryClient.clear()
    server.use(
      http.get('/api/networks', () => HttpResponse.json(NETWORKS)),
      http.get('/api/credentials', () => HttpResponse.json(CREDENTIALS)),
      http.get('/api/networks/1/scan-status', () =>
        HttpResponse.json({
          network_id: 1,
          status: 'idle',
          total_hosts: 0,
          scanned_hosts: 0,
          started_at: null,
          finished_at: null,
        }),
      ),
    )
  })

  it('links to the network map', async () => {
    renderPage()
    const link = await screen.findByRole('link', { name: 'Map' })
    expect(link).toHaveAttribute('href', '/networks/1/map')
  })

  it('deletes a network after confirmation', async () => {
    let deleted = false
    server.use(
      http.delete('/api/networks/1', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(deleted).toBe(true))
  })

  it('expands a credentials panel and can bind a credential to the network', async () => {
    const bindings: { id: number; network_id: number; credential_id: number; priority: number; created_at: string }[] = []
    server.use(
      http.get('/api/networks/1/credentials', () => HttpResponse.json(bindings)),
      http.post('/api/networks/1/credentials', async ({ request }) => {
        const body = (await request.json()) as { credential_id: number; priority: number }
        const binding = { id: 1, network_id: 1, created_at: '', ...body }
        bindings.push(binding)
        return HttpResponse.json(binding, { status: 201 })
      }),
    )

    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Credentials' }))
    expect(await screen.findByText(/None bound/)).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByRole('combobox'), '5')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => expect(bindings).toHaveLength(1))
  })

  it('shows live scan progress and disables the trigger while scanning', async () => {
    server.use(
      http.get('/api/networks/1/scan-status', () =>
        HttpResponse.json({
          network_id: 1,
          status: 'scanning',
          total_hosts: 254,
          scanned_hosts: 40,
          started_at: '2026-01-01T00:00:00Z',
          finished_at: null,
        }),
      ),
    )

    renderPage()

    expect(await screen.findByText('Scanning… 40/254')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Scanning…' })).toBeDisabled()
  })
})
