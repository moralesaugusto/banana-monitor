import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import type { Service } from '../api/types'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { ServicesPage } from './ServicesPage'

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <ServicesPage />
    </QueryClientProvider>,
  )
}

describe('ServicesPage', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('offers dns and dhcp as service type options', async () => {
    server.use(
      http.get('/api/devices', () => HttpResponse.json([])),
      http.get('/api/services', () => HttpResponse.json([])),
    )
    renderPage()

    expect(await screen.findByText('No services yet.')).toBeInTheDocument()
    const typeSelect = screen.getByLabelText('Type') as HTMLSelectElement
    const optionValues = Array.from(typeSelect.options).map((o) => o.value)
    expect(optionValues).toEqual(
      expect.arrayContaining(['http', 'https', 'tcp', 'dns', 'dhcp', 'proxmox_vm', 'proxmox_lxc', 'systemd_unit']),
    )
  })

  it('creates a dns check service with host/port/query_name/record_type config', async () => {
    const services: Service[] = []
    let capturedBody: Record<string, unknown> | null = null

    server.use(
      http.get('/api/devices', () => HttpResponse.json([])),
      http.get('/api/services', () => HttpResponse.json(services)),
      http.post('/api/services', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        capturedBody = body
        const service: Service = {
          id: 1,
          device_id: null,
          name: body.name as string,
          service_type: body.service_type as Service['service_type'],
          config: (body.config as Record<string, unknown>) ?? {},
          status: 'unknown',
          managed: true,
          port: null,
          source: 'manual',
          fingerprint: null,
          last_checked_at: null,
          last_latency_ms: null,
          device_vendor: null,
        }
        services.push(service)
        return HttpResponse.json(service, { status: 201 })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('No services yet.')).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('pve-web'), 'lan-dns')
    await user.selectOptions(screen.getByLabelText('Type'), 'dns')

    await user.type(screen.getByPlaceholderText('192.168.1.1'), '192.168.1.1')
    await user.type(screen.getByPlaceholderText('53'), '53')
    await user.type(screen.getByPlaceholderText('example.com'), 'router.lan')
    await user.type(screen.getByPlaceholderText('A'), 'A')

    await user.click(screen.getByRole('button', { name: 'Add service' }))

    await waitFor(() => {
      expect(screen.getByText('lan-dns')).toBeInTheDocument()
    })

    expect(capturedBody).toMatchObject({
      service_type: 'dns',
      config: { host: '192.168.1.1', port: 53, query_name: 'router.lan', record_type: 'A' },
    })
  })

  it('creates a dhcp check service with host/timeout_seconds config', async () => {
    const services: Service[] = []
    let capturedBody: Record<string, unknown> | null = null

    server.use(
      http.get('/api/devices', () => HttpResponse.json([])),
      http.get('/api/services', () => HttpResponse.json(services)),
      http.post('/api/services', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        capturedBody = body
        const service: Service = {
          id: 2,
          device_id: null,
          name: body.name as string,
          service_type: body.service_type as Service['service_type'],
          config: (body.config as Record<string, unknown>) ?? {},
          status: 'unknown',
          managed: true,
          port: null,
          source: 'manual',
          fingerprint: null,
          last_checked_at: null,
          last_latency_ms: null,
          device_vendor: null,
        }
        services.push(service)
        return HttpResponse.json(service, { status: 201 })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('No services yet.')).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('pve-web'), 'lan-dhcp')
    await user.selectOptions(screen.getByLabelText('Type'), 'dhcp')

    await user.type(screen.getByPlaceholderText('192.168.1.1'), '192.168.1.1')
    await user.type(screen.getByPlaceholderText('2'), '2.5')

    await user.click(screen.getByRole('button', { name: 'Add service' }))

    await waitFor(() => {
      expect(screen.getByText('lan-dhcp')).toBeInTheDocument()
    })

    expect(capturedBody).toMatchObject({
      service_type: 'dhcp',
      config: { host: '192.168.1.1', timeout_seconds: 2.5 },
    })
  })

  it('shows the parent device vendor in its own column', async () => {
    const services: Service[] = [
      {
        id: 3,
        device_id: 7,
        name: 'ssh',
        service_type: 'tcp',
        config: { host: '192.168.1.50', port: 22 },
        status: 'up',
        managed: true,
          port: null,
          source: 'manual',
          fingerprint: null,
        last_checked_at: null,
        last_latency_ms: null,
        device_vendor: 'Raspberry Pi Trading Ltd',
      },
    ]

    server.use(
      http.get('/api/devices', () => HttpResponse.json([{ id: 7, display_name: 'pi' }])),
      http.get('/api/services', () => HttpResponse.json(services)),
    )

    renderPage()

    expect(await screen.findByText('Raspberry Pi Trading Ltd')).toBeInTheDocument()
  })

  it('sends filter and sort params to the API', async () => {
    const urls: string[] = []
    server.use(
      http.get('/api/devices', () => HttpResponse.json([])),
      http.get('/api/services', ({ request }) => {
        urls.push(request.url)
        return HttpResponse.json([])
      }),
    )
    renderPage()
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText('Filter status'), 'down')
    await user.click(screen.getByRole('button', { name: 'Port' }))

    await waitFor(() => {
      const last = new URL(urls[urls.length - 1])
      expect(last.searchParams.get('status')).toBe('down')
      expect(last.searchParams.get('sort')).toBe('port')
    })
  })

  it('selects all, bulk deletes, and groups by host', async () => {
    const svc = (id: number, name: string, device_id: number | null): Service => ({
      id, device_id, name, service_type: 'tcp', config: {}, status: 'up', managed: false,
      port: id, source: 'scan', fingerprint: null, last_checked_at: null, last_latency_ms: null, device_vendor: null,
    })
    let bulkBody: Record<string, unknown> | null = null
    window.confirm = () => true
    server.use(
      http.get('/api/devices', () =>
        HttpResponse.json([{ id: 1, display_name: 'nas' }, { id: 2, display_name: 'router' }]),
      ),
      http.get('/api/services', () =>
        HttpResponse.json([svc(1, 'a', 1), svc(2, 'b', 1), svc(3, 'c', 2)]),
      ),
      http.post('/api/services/bulk', async ({ request }) => {
        bulkBody = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ affected: 3 })
      }),
    )
    renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByLabelText('Group by host'))
    expect(await screen.findByLabelText('Select group nas')).toBeInTheDocument()
    expect(screen.getByLabelText('Select group router')).toBeInTheDocument()

    await user.click(screen.getByLabelText('Select all'))
    expect(screen.getByText('3 selected')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Delete selected' }))

    await waitFor(() => expect(bulkBody).toEqual({ ids: [1, 2, 3], action: 'delete' }))
  })
})
