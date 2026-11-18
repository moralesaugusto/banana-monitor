import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { Device, Service } from '../api/types'
import type { OverviewSummary } from '../api/overview'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { OverviewPage } from './OverviewPage'

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const overview: OverviewSummary = {
  devices: { up: 10, down: 2, degraded: 1, unknown: 0 },
  services: { up: 8, down: 1, degraded: 0, unknown: 0 },
  integrations_ok: 2,
  integrations_error: 1,
  firing_alerts: [],
  recent_events: [
    {
      id: 1,
      ts: '2026-11-17T10:00:00Z',
      source: 'device',
      severity: 'info',
      category: 'status',
      message: 'Device came up',
      related_entity_type: null,
      related_entity_id: null,
    },
  ],
}

const device: Device = {
  id: 1,
  site_id: 1,
  network_id: null,
  hostname: null,
  display_name: 'router.lan',
  primary_ip: '192.168.1.1',
  device_type: 'other',
  status: 'down',
  managed: true,
  tags: [],
  notes: null,
  first_seen_at: '2026-01-01T00:00:00Z',
  last_seen_at: null,
  inactive: false,
}

const service: Service = {
  id: 1,
  device_id: 1,
  name: '192.168.1.1:443',
  service_type: 'https',
  config: {},
  status: 'up',
  managed: true,
  port: 443,
  source: 'manual',
  fingerprint: null,
  last_checked_at: '2026-11-17T10:00:00Z',
  last_latency_ms: 123.4,
  device_vendor: null,
}

function mockDashboard() {
  server.use(
    http.get('/api/overview', () => HttpResponse.json(overview)),
    http.get('/api/overview/health-trend', () => HttpResponse.json({ buckets: [] })),
    http.get('/api/devices', () => HttpResponse.json([device])),
    http.get('/api/services', () => HttpResponse.json([service])),
  )
}

describe('OverviewPage', () => {
  beforeEach(() => queryClient.clear())

  it('shows a loading state before the summary arrives', () => {
    server.use(http.get('/api/overview', () => new Promise(() => {})))
    renderPage()
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('splits the dashboard into separate bento cards, each with its own data', async () => {
    mockDashboard()
    renderPage()

    expect(await screen.findByText('Network overview')).toBeInTheDocument()
    expect(screen.getByText('24h health trend')).toBeInTheDocument()
    expect(screen.getByText('Needs attention')).toBeInTheDocument()
    expect(screen.getByText('Slowest services')).toBeInTheDocument()
    expect(screen.getByText('Recent events')).toBeInTheDocument()

    // Needs attention: the down device shows up with a link to its detail page.
    const brokenLink = await screen.findByRole('link', { name: /router\.lan/ })
    expect(brokenLink).toHaveAttribute('href', '/devices/1')

    // Slowest services: the up service with latency shows up with its latency.
    expect(await screen.findByText('192.168.1.1:443')).toBeInTheDocument()
    expect(screen.getByText('123 ms')).toBeInTheDocument()

    // Recent events: the event message is shown.
    expect(screen.getByText(/Device came up/)).toBeInTheDocument()
  })

  it('shows the computed health score and no pending alerts when none are firing', async () => {
    mockDashboard()
    renderPage()

    // devices: 10 up, 2 down, 1 degraded -> (10 + 0.5)/13 = ~81%; services: 8 up, 1 down -> 8/9 = ~89%; avg ~85
    expect(await screen.findByRole('img', { name: /Health score: 85/ })).toBeInTheDocument()
    expect(screen.getByText('No pending alerts.')).toBeInTheDocument()
  })
})
