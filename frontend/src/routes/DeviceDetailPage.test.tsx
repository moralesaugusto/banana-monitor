import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { DeviceDetailPage } from './DeviceDetailPage'

describe('DeviceDetailPage', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('shows the full service info for this host only', async () => {
    const service = {
      config: {}, status: 'up', managed: true, source: 'scan', last_checked_at: null,
      last_latency_ms: 4.2, device_vendor: null,
    }
    server.use(
      http.get('/api/devices/1', () =>
        HttpResponse.json({
          id: 1, site_id: 1, network_id: null, hostname: null, display_name: 'pve1', primary_ip: '10.0.0.1',
          device_type: 'linux', status: 'up', managed: true, tags: [], notes: null, first_seen_at: '', last_seen_at: null,
          addresses: [], services: [], metrics: {},
        }),
      ),
      http.get('/api/services', () =>
        HttpResponse.json([
          { ...service, id: 1, device_id: 1, name: 'ssh', service_type: 'tcp', port: 22,
            fingerprint: { product: 'OpenSSH', version: '10.0p2', banner: 'SSH-2.0-OpenSSH_10.0p2' } },
          { ...service, id: 2, device_id: 2, name: 'other-host-svc', service_type: 'tcp', port: 80, fingerprint: null },
        ]),
      ),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/devices/1']}>
          <Routes>
            <Route path="devices/:id" element={<DeviceDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('ssh')).toBeInTheDocument()
    expect(screen.getByText('OpenSSH 10.0p2')).toBeInTheDocument()
    expect(screen.getByText('SSH-2.0-OpenSSH_10.0p2')).toBeInTheDocument()
    expect(screen.getByText('4.2 ms')).toBeInTheDocument()
    expect(screen.queryByText('other-host-svc')).not.toBeInTheDocument()
  })

  it('describes the scan tool and reports how many services were fingerprinted', async () => {
    server.use(
      http.get('/api/devices/1', () =>
        HttpResponse.json({
          id: 1, site_id: 1, network_id: null, hostname: null, display_name: 'pve1', primary_ip: '10.0.0.1',
          device_type: 'linux', status: 'up', managed: true, tags: [], notes: null, first_seen_at: '', last_seen_at: null,
          addresses: [], services: [], metrics: {},
        }),
      ),
      http.get('/api/services', () => HttpResponse.json([])),
      http.post('/api/devices/1/rescan', () => HttpResponse.json({ updated: 3 })),
    )
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/devices/1']}>
          <Routes>
            <Route path="devices/:id" element={<DeviceDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText(/scans every port on this host with nmap/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Scan all services' }))
    expect(await screen.findByText('Scan finished: 3 service(s) fingerprinted.')).toBeInTheDocument()
  })
})
