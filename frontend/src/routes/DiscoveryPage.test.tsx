import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { DiscoveredCandidate } from '../api/discovery'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { DiscoveryPage } from './DiscoveryPage'

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DiscoveryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DiscoveryPage', () => {
  let autoAccept = false
  const autoAcceptPuts: unknown[] = []

  beforeEach(() => {
    queryClient.clear()
    autoAccept = false
    autoAcceptPuts.length = 0
    server.use(
      http.get('/api/system/discovery-settings', () => HttpResponse.json({ auto_accept_services: autoAccept })),
      http.put('/api/system/discovery-settings', async ({ request }) => {
        const body = (await request.json()) as { auto_accept_services: boolean }
        autoAcceptPuts.push(body)
        autoAccept = body.auto_accept_services
        return HttpResponse.json({ auto_accept_services: autoAccept })
      }),
    )
  })

  it('turns automatic acceptance of services on', async () => {
    server.use(http.get('/api/discovery/candidates', () => HttpResponse.json([])))
    renderPage()

    const box = await screen.findByRole('checkbox', { name: /Automatically accept services/ })
    expect(box).not.toBeChecked()
    await userEvent.click(box)

    await waitFor(() => expect(autoAcceptPuts).toEqual([{ auto_accept_services: true }]))
    await waitFor(() => expect(box).toBeChecked())
  })

  it('shows a suggested-integration badge and a configure-as link for a fingerprinted candidate', async () => {
    const candidates: DiscoveredCandidate[] = [
      {
        id: 1,
        candidate_type: 'service',
        discovered_via: 'http_probe',
        network_id: 1,
        raw_attributes: {
          ip: '192.168.1.20',
          port: 3000,
          protocol: 'http',
          suggested_integration_type: 'adguard_home',
        },
        first_seen_at: new Date().toISOString(),
        last_seen_at: new Date().toISOString(),
        times_seen: 3,
        status: 'pending',
        resulting_device_id: null,
        resulting_service_id: null,
      },
    ]

    server.use(http.get('/api/discovery/candidates', () => HttpResponse.json(candidates)))

    renderPage()

    expect(await screen.findByText('Looks like: AdGuard Home')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /Configure as AdGuard Home/ })
    expect(link).toHaveAttribute('href', '/integrations')
  })

  it('shows the Generic (SSH) suggestion for a port-22 candidate regardless of OS', async () => {
    const candidates: DiscoveredCandidate[] = [
      {
        id: 3,
        candidate_type: 'service',
        discovered_via: 'tcp_probe',
        network_id: 1,
        raw_attributes: {
          ip: '192.168.1.40',
          port: 22,
          protocol: 'tcp',
          suggested_integration_type: 'generic_ssh',
        },
        first_seen_at: new Date().toISOString(),
        last_seen_at: new Date().toISOString(),
        times_seen: 1,
        status: 'pending',
        resulting_device_id: null,
        resulting_service_id: null,
      },
    ]

    server.use(http.get('/api/discovery/candidates', () => HttpResponse.json(candidates)))

    renderPage()

    expect(await screen.findByText('Looks like: Generic (SSH)')).toBeInTheDocument()
  })

  it('accepting a plain candidate without a suggestion keeps working and shows no configure-as link', async () => {
    const candidates: DiscoveredCandidate[] = [
      {
        id: 2,
        candidate_type: 'service',
        discovered_via: 'tcp_probe',
        network_id: 1,
        raw_attributes: { ip: '192.168.1.30', port: 22, protocol: 'tcp' },
        first_seen_at: new Date().toISOString(),
        last_seen_at: new Date().toISOString(),
        times_seen: 1,
        status: 'pending',
        resulting_device_id: null,
        resulting_service_id: null,
      },
    ]

    server.use(http.get('/api/discovery/candidates', () => HttpResponse.json(candidates)))

    renderPage()

    expect(await screen.findByText(/192\.168\.1\.30:22/)).toBeInTheDocument()
    expect(screen.queryByText(/Looks like:/)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Configure as/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept' })).toBeInTheDocument()
  })

  it('accepts every pending candidate with its default type/config via Accept all', async () => {
    const candidates: DiscoveredCandidate[] = [
      {
        id: 10,
        candidate_type: 'service',
        discovered_via: 'tcp_probe',
        network_id: 1,
        raw_attributes: { ip: '192.168.1.40', port: 443, protocol: 'https' },
        first_seen_at: new Date().toISOString(),
        last_seen_at: new Date().toISOString(),
        times_seen: 1,
        status: 'pending',
        resulting_device_id: null,
        resulting_service_id: null,
      },
      {
        id: 11,
        candidate_type: 'service',
        discovered_via: 'tcp_probe',
        network_id: 1,
        raw_attributes: { ip: '192.168.1.41', port: 22, protocol: 'tcp' },
        first_seen_at: new Date().toISOString(),
        last_seen_at: new Date().toISOString(),
        times_seen: 1,
        status: 'pending',
        resulting_device_id: null,
        resulting_service_id: null,
      },
    ]
    server.use(http.get('/api/discovery/candidates', () => HttpResponse.json(candidates)))

    const accepted: { id: number; body: unknown }[] = []
    server.use(
      http.post('/api/discovery/candidates/:id/accept-service', async ({ params, request }) => {
        accepted.push({ id: Number(params.id), body: await request.json() })
        return HttpResponse.json({ id: 999, name: 'x', service_type: 'tcp', status: 'unknown' }, { status: 201 })
      }),
    )

    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /Accept all \(2\)/ }))

    await waitFor(() => expect(accepted).toHaveLength(2))
    expect(accepted.map((a) => a.id).sort()).toEqual([10, 11])
    const byId = Object.fromEntries(accepted.map((a) => [a.id, a.body as { service_type: string }]))
    expect(byId[10].service_type).toBe('https')
    expect(byId[11].service_type).toBe('tcp')
  })
})
