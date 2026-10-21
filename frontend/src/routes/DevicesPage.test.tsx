import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import type { Device, DeviceListItem, Network } from '../api/types'
import { DevicesPage } from './DevicesPage'

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DevicesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DevicesPage', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('creates a device via the form and shows it in the list', async () => {
    const devices: Device[] = []

    server.use(
      http.get('/api/networks', () => HttpResponse.json([])),
      http.get('/api/devices', () => HttpResponse.json(devices)),
      http.post('/api/devices', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        const device: Device = {
          id: 1,
          site_id: 1,
          network_id: null,
          hostname: null,
          display_name: body.display_name as string,
          primary_ip: (body.primary_ip as string | null) ?? null,
          device_type: body.device_type as Device['device_type'],
          status: 'unknown',
          managed: true,
          tags: [],
          notes: null,
          first_seen_at: new Date().toISOString(),
          last_seen_at: null,
          inactive: false,
        }
        devices.push(device)
        return HttpResponse.json(device, { status: 201 })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('No devices yet.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'New device' }))
    await user.type(screen.getByPlaceholderText('pve1'), 'pve1')
    await user.click(screen.getByRole('button', { name: 'Add device' }))

    await waitFor(() => {
      expect(screen.getByRole('link', { name: 'pve1' })).toBeInTheDocument()
    })

    const row = screen.getByRole('link', { name: 'pve1' }).closest('tr')!
    expect(within(row).getByText('unknown')).toBeInTheDocument()
  })

  it('filters devices by network', async () => {
    const networks: Network[] = [
      { id: 1, site_id: 1, name: 'LAN', cidr: '192.168.1.0/24', vlan_id: null, description: null },
      { id: 2, site_id: 1, name: 'Guest', cidr: '192.168.2.0/24', vlan_id: null, description: null },
    ]
    const base = {
      site_id: 1, hostname: null, primary_ip: null, device_type: 'linux' as const, status: 'unknown' as const,
      managed: true, tags: [], notes: null, first_seen_at: '', last_seen_at: null, inactive: false,
    }
    const devices: DeviceListItem[] = [
      { ...base, id: 1, display_name: 'lan-host', network_id: 1, network_name: 'LAN' },
      { ...base, id: 2, display_name: 'guest-host', network_id: 2, network_name: 'Guest' },
      { ...base, id: 3, display_name: 'no-network-host', network_id: null, network_name: null },
    ]
    server.use(
      http.get('/api/networks', () => HttpResponse.json(networks)),
      http.get('/api/devices', () => HttpResponse.json(devices)),
    )

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('link', { name: 'lan-host' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'guest-host' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'no-network-host' })).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Filter by network'), 'LAN (1)')
    expect(screen.getByRole('link', { name: 'lan-host' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'guest-host' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'no-network-host' })).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Filter by network'), 'Unassigned (1)')
    expect(screen.getByRole('link', { name: 'no-network-host' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'lan-host' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'guest-host' })).not.toBeInTheDocument()
  })

  it('shows an Inactive badge for a device down and unseen for days', async () => {
    const base = {
      site_id: 1, hostname: null, primary_ip: null, device_type: 'linux' as const, status: 'down' as const,
      managed: true, tags: [], notes: null, first_seen_at: '', last_seen_at: null, network_id: null, network_name: null,
    }
    const devices: DeviceListItem[] = [
      { ...base, id: 1, display_name: 'gone-host', inactive: true },
      { ...base, id: 2, display_name: 'just-down-host', inactive: false },
    ]
    server.use(
      http.get('/api/networks', () => HttpResponse.json([])),
      http.get('/api/devices', () => HttpResponse.json(devices)),
    )

    renderPage()

    const inactiveRow = (await screen.findByRole('link', { name: 'gone-host' })).closest('tr')!
    expect(within(inactiveRow).getByText('Inactive')).toBeInTheDocument()

    const downRow = screen.getByRole('link', { name: 'just-down-host' }).closest('tr')!
    expect(within(downRow).queryByText('Inactive')).not.toBeInTheDocument()
  })
})
