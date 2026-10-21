import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { NetworkGraphPage } from './NetworkGraphPage'

const topology = {
  truncated: false,
  nodes: [
    { id: 'network:1', kind: 'network', label: 'LAN1', subtitle: '192.168.1.0/24', status: null, entity_id: 1, meta: {} },
    { id: 'device:5', kind: 'device', label: 'nas', subtitle: '192.168.1.5', status: 'up', entity_id: 5, meta: { vendor: 'Synology' } },
    { id: 'service:9', kind: 'service', label: 'tcp:22', subtitle: 'OpenSSH 9.2', status: 'up', entity_id: 9, meta: {} },
  ],
  edges: [
    { source: 'network:1', target: 'device:5', relation: 'contains' },
    { source: 'device:5', target: 'service:9', relation: 'runs' },
  ],
}

describe('NetworkGraphPage', () => {
  beforeEach(() => {
    queryClient.clear()
    server.use(
      http.get('/api/networks', () => HttpResponse.json([{ id: 1, name: 'LAN1', cidr: '192.168.1.0/24' }])),
      http.get('/api/topology', () => HttpResponse.json(topology)),
    )
  })

  it('draws nodes and shows what a selected node is connected to', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <NetworkGraphPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const user = userEvent.setup()

    await waitFor(() => expect(document.querySelectorAll('svg[aria-label="Network graph"] circle').length).toBeGreaterThanOrEqual(3))

    const deviceNode = Array.from(document.querySelectorAll('svg[aria-label="Network graph"] g[class*="cursor-pointer"]')).find(
      (g) => g.textContent?.includes('nas'),
    )!
    await user.click(deviceNode)

    expect(await screen.findByText('Connected (2)')).toBeInTheDocument()
    expect(screen.getByText('Synology')).toBeInTheDocument()
  })
})
