import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { Network } from '../api/types'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { NetworkMapPage } from './NetworkMapPage'

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/networks/:id/map" element={<NetworkMapPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const NETWORKS: Network[] = [
  { id: 1, site_id: 1, name: 'LAN', cidr: '192.168.1.0/30', vlan_id: null, description: null },
]

describe('NetworkMapPage', () => {
  beforeEach(() => {
    queryClient.clear()
    server.use(http.get('/api/networks', () => HttpResponse.json(NETWORKS)))
  })

  it('renders one cell per address for a small network', async () => {
    server.use(
      http.get('/api/networks/1/map', () =>
        HttpResponse.json({
          network_id: 1,
          cidr: '192.168.1.0/30',
          total_addresses: 2,
          truncated: false,
          addresses: [
            { ip: '192.168.1.1', status: 'up', device_id: 1, display_name: 'router', managed: true },
            { ip: '192.168.1.2', status: null, device_id: null, display_name: null, managed: null },
          ],
          summary: null,
        }),
      ),
    )

    renderAt('/networks/1/map')

    expect(await screen.findByRole('img', { name: /network address map/i })).toBeInTheDocument()
    expect(screen.getByText('router')).toBeInTheDocument()
  })

  it('shows status counts instead of a grid when the map is truncated', async () => {
    server.use(
      http.get('/api/networks/1/map', () =>
        HttpResponse.json({
          network_id: 1,
          cidr: '10.0.0.0/16',
          total_addresses: 65534,
          truncated: true,
          addresses: [],
          summary: { up: 3, down: 1, degraded: 0, unknown: 0, unmanaged: 5 },
        }),
      ),
    )

    renderAt('/networks/1/map')

    expect(await screen.findByText(/too many to render one cell per address/)).toBeInTheDocument()
    expect(screen.getByText(/up: 3/)).toBeInTheDocument()
    expect(screen.getByText(/unmanaged: 5/)).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /network address map/i })).not.toBeInTheDocument()
  })
})
