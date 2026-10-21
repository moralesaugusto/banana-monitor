import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { Credential } from '../api/credentials'
import type { Integration, IntegrationTypeInfo } from '../api/integrations'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { IntegrationsPage } from './IntegrationsPage'

function renderPage(initialEntries: Array<string | { pathname: string; state?: unknown }> = ['/integrations']) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <IntegrationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const DEMO_TYPE: IntegrationTypeInfo = {
  type_key: 'demo',
  display_name: 'Demo Plugin',
  config_schema: {
    type: 'object',
    properties: {
      host: { type: 'string', title: 'Host' },
      port: { type: 'integer', title: 'Port', default: 8080 },
      verify_tls: { type: 'boolean', title: 'Verify TLS', default: false },
      mode: { type: 'string', title: 'Mode', enum: ['fast', 'slow'], default: 'fast' },
    },
    required: ['host'],
  },
  credential_schema: null,
}

const LINUX_SSH_TYPE: IntegrationTypeInfo = {
  type_key: 'generic_ssh',
  display_name: 'Generic (SSH)',
  config_schema: {
    type: 'object',
    properties: {
      device_id: { anyOf: [{ type: 'integer' }, { type: 'null' }], title: 'Device Id' },
      host: { anyOf: [{ type: 'string' }, { type: 'null' }], title: 'Host' },
      port: { type: 'integer', title: 'Port', default: 22 },
    },
  },
  credential_schema: {
    type: 'object',
    properties: {
      username: { type: 'string', title: 'Username' },
      private_key: { anyOf: [{ type: 'string' }, { type: 'null' }], title: 'Private Key' },
      passphrase: { anyOf: [{ type: 'string' }, { type: 'null' }], title: 'Passphrase' },
      password: { anyOf: [{ type: 'string' }, { type: 'null' }], title: 'Password' },
    },
    required: ['username'],
  },
}

describe('IntegrationsPage', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('creates a credential inline and attaches it to a new integration', async () => {
    const credentials: Credential[] = []
    const integrations: Integration[] = []
    let capturedIntegrationBody: Record<string, unknown> | null = null

    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([])),
      http.get('/api/credentials', () => HttpResponse.json(credentials)),
      http.get('/api/integrations', () => HttpResponse.json(integrations)),
      http.post('/api/credentials', async ({ request }) => {
        const body = (await request.json()) as { label: string; credential_type: string }
        const credential: Credential = {
          id: 1,
          label: body.label,
          credential_type: body.credential_type as Credential['credential_type'],
          created_at: new Date().toISOString(),
          rotated_at: null,
          last_used_at: null,
        }
        credentials.push(credential)
        return HttpResponse.json(credential, { status: 201 })
      }),
      http.post('/api/integrations', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        capturedIntegrationBody = body
        const integration: Integration = {
          id: 1,
          integration_type: body.integration_type as string,
          name: body.name as string,
          config: (body.config as Record<string, unknown>) ?? {},
          credential_id: (body.credential_id as number | null) ?? null,
          enabled: true,
          status: 'unknown',
          last_run_at: null,
          last_error: null,
        }
        integrations.push(integration)
        return HttpResponse.json(integration, { status: 201 })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('No integrations configured yet.')).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('proxmox'), 'proxmox')
    await user.type(screen.getByPlaceholderText('pve1'), 'pve1')

    await user.click(screen.getByRole('button', { name: '+ New credential' }))
    await user.type(screen.getByPlaceholderText('pve1-token'), 'pve1-token')

    await user.click(screen.getByRole('button', { name: 'Add integration' }))

    await waitFor(() => {
      expect(screen.getByText('pve1')).toBeInTheDocument()
    })

    expect(capturedIntegrationBody).toMatchObject({ credential_id: 1, name: 'pve1' })
    expect(screen.queryByText(/hunter2|secret/i)).not.toBeInTheDocument()
  })

  it('renders a typed field per JSON Schema type and submits their values as config', async () => {
    const integrations: Integration[] = []
    let capturedBody: Record<string, unknown> | null = null

    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([DEMO_TYPE])),
      http.get('/api/credentials', () => HttpResponse.json([])),
      http.get('/api/integrations', () => HttpResponse.json(integrations)),
      http.post('/api/integrations', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        capturedBody = body
        const integration: Integration = {
          id: 1,
          integration_type: body.integration_type as string,
          name: body.name as string,
          config: (body.config as Record<string, unknown>) ?? {},
          credential_id: null,
          enabled: true,
          status: 'unknown',
          last_run_at: null,
          last_error: null,
        }
        integrations.push(integration)
        return HttpResponse.json(integration, { status: 201 })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('No integrations configured yet.')).toBeInTheDocument()

    await user.selectOptions(screen.getByText('Select…').closest('select')!, 'demo')
    await user.type(screen.getByPlaceholderText('pve1'), 'demo-instance')

    // string field
    const hostInput = screen.getByRole('textbox', { name: /Host/ })
    await user.type(hostInput, '192.168.1.50')

    // number field: pre-filled from schema default
    const portInput = screen.getByRole('spinbutton', { name: /Port/ })
    expect(portInput).toHaveValue(8080)
    await user.clear(portInput)
    await user.type(portInput, '9000')

    // boolean field
    const verifyTlsCheckbox = screen.getByRole('checkbox', { name: /Verify TLS/ })
    expect(verifyTlsCheckbox).not.toBeChecked()
    await user.click(verifyTlsCheckbox)

    // enum field: pre-filled from schema default
    const modeSelect = screen.getByRole('combobox', { name: /Mode/ })
    expect(modeSelect).toHaveValue('fast')
    await user.selectOptions(modeSelect, 'slow')

    await user.click(screen.getByRole('button', { name: 'Add integration' }))

    await waitFor(() => {
      expect(screen.getByText('demo-instance')).toBeInTheDocument()
    })

    expect(capturedBody).toMatchObject({
      integration_type: 'demo',
      config: {
        host: '192.168.1.50',
        port: 9000,
        verify_tls: true,
        mode: 'slow',
      },
    })
  })

  it('blocks submission when a required typed field is left empty', async () => {
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([DEMO_TYPE])),
      http.get('/api/credentials', () => HttpResponse.json([])),
      http.get('/api/integrations', () => HttpResponse.json([])),
    )

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('No integrations configured yet.')).toBeInTheDocument()
    await user.selectOptions(screen.getByText('Select…').closest('select')!, 'demo')
    await user.type(screen.getByPlaceholderText('pve1'), 'demo-instance')

    await user.click(screen.getByRole('button', { name: 'Add integration' }))

    expect(await screen.findByText('Fill in all required config fields.')).toBeInTheDocument()
  })

  it('derives the new credential type from the selected integration type, with no duplicate Type field', async () => {
    let capturedCredentialBody: Record<string, unknown> | null = null
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([])),
      http.get('/api/credentials', () => HttpResponse.json([])),
      http.get('/api/integrations', () => HttpResponse.json([])),
      http.post('/api/credentials', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        capturedCredentialBody = body
        const credential: Credential = {
          id: 1,
          label: body.label as string,
          credential_type: body.credential_type as Credential['credential_type'],
          created_at: new Date().toISOString(),
          rotated_at: null,
          last_used_at: null,
        }
        return HttpResponse.json(credential, { status: 201 })
      }),
      http.post('/api/integrations', () =>
        HttpResponse.json(
          {
            id: 1,
            integration_type: 'generic_ssh',
            name: 'host1',
            config: {},
            credential_id: 1,
            enabled: true,
            status: 'unknown',
            last_run_at: null,
            last_error: null,
          },
          { status: 201 },
        ),
      ),
    )

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('No integrations configured yet.')).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText('proxmox'), 'generic_ssh')
    await user.type(screen.getByPlaceholderText('pve1'), 'host1')

    await user.click(screen.getByRole('button', { name: '+ New credential' }))
    // Only one "Type" field exists in the form: the integration type picked above. The
    // new-credential panel must not render a second, separate one.
    const form = screen.getByPlaceholderText('pve1-token').closest('form')!
    expect(within(form).getAllByText('Type')).toHaveLength(1)
    expect(screen.getByText(/Saved as a ssh_key credential/)).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('pve1-token'), 'wallet-cred')
    await user.click(screen.getByRole('button', { name: 'Add integration' }))

    await waitFor(() => {
      expect(capturedCredentialBody).toMatchObject({ credential_type: 'ssh_key' })
    })
  })

  it('shows a Wallet badge for an integration saved with a credential but no host', async () => {
    const integrations: Integration[] = [
      {
        id: 1,
        integration_type: 'generic_ssh',
        name: 'ssh-wallet',
        config: {},
        credential_id: 1,
        enabled: true,
        status: 'unknown',
        last_run_at: null,
        last_error: null,
      },
    ]
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([])),
      http.get('/api/credentials', () => HttpResponse.json([])),
      http.get('/api/integrations', () => HttpResponse.json(integrations)),
    )

    renderPage()

    expect(await screen.findByText('ssh-wallet')).toBeInTheDocument()
    expect(screen.getByText('Wallet')).toBeInTheDocument()
  })

  it('toggles an integration enabled/disabled without deleting it', async () => {
    const integrations: Integration[] = [
      {
        id: 1,
        integration_type: 'generic_ssh',
        name: 'ssh-wallet',
        config: {},
        credential_id: 1,
        enabled: true,
        status: 'unknown',
        last_run_at: null,
        last_error: null,
      },
    ]
    let patchedBody: Record<string, unknown> | null = null
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([])),
      http.get('/api/credentials', () => HttpResponse.json([])),
      http.get('/api/integrations', () => HttpResponse.json(integrations)),
      http.patch('/api/integrations/1', async ({ request }) => {
        patchedBody = (await request.json()) as Record<string, unknown>
        integrations[0] = { ...integrations[0], enabled: patchedBody.enabled as boolean }
        return HttpResponse.json(integrations[0])
      }),
    )

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('ssh-wallet')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Disable' }))

    await waitFor(() => {
      expect(patchedBody).toMatchObject({ enabled: false })
    })
    expect(await screen.findByRole('button', { name: 'Enable' })).toBeInTheDocument()
  })

  it('labels a password-filled generic_ssh credential as ssh_password, not ssh_key', async () => {
    let capturedCredentialBody: Record<string, unknown> | null = null
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([LINUX_SSH_TYPE])),
      http.get('/api/credentials', () => HttpResponse.json([])),
      http.get('/api/integrations', () => HttpResponse.json([])),
      http.get('/api/devices', () => HttpResponse.json([])),
      http.post('/api/credentials', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        capturedCredentialBody = body
        const credential: Credential = {
          id: 1,
          label: body.label as string,
          credential_type: body.credential_type as Credential['credential_type'],
          created_at: new Date().toISOString(),
          rotated_at: null,
          last_used_at: null,
        }
        return HttpResponse.json(credential, { status: 201 })
      }),
      http.post('/api/integrations', () =>
        HttpResponse.json(
          {
            id: 1,
            integration_type: 'generic_ssh',
            name: 'host1',
            config: {},
            credential_id: 1,
            enabled: true,
            status: 'unknown',
            last_run_at: null,
            last_error: null,
          },
          { status: 201 },
        ),
      ),
    )

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('No integrations configured yet.')).toBeInTheDocument()
    await user.selectOptions(screen.getByText('Select…').closest('select')!, 'generic_ssh')
    await user.type(screen.getByPlaceholderText('pve1'), 'host1')

    await user.click(screen.getByRole('button', { name: '+ New credential' }))
    await user.type(await screen.findByLabelText(/^Username/), 'testuser')
    await user.type(screen.getByLabelText('Password'), 'testpass123')

    expect(screen.getByText(/Saved as a ssh_password credential/)).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('pve1-token'), 'password-cred')
    await user.click(screen.getByRole('button', { name: 'Add integration' }))

    await waitFor(() => {
      expect(capturedCredentialBody).toMatchObject({ credential_type: 'ssh_password' })
    })
  })

  it('renders a Device picker instead of a bare number input for device_id', async () => {
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([LINUX_SSH_TYPE])),
      http.get('/api/credentials', () => HttpResponse.json([])),
      http.get('/api/integrations', () => HttpResponse.json([])),
      http.get('/api/devices', () =>
        HttpResponse.json([
          { id: 5, display_name: 'pve1', primary_ip: '192.168.1.10' },
          { id: 6, display_name: 'nas', primary_ip: '192.168.1.11' },
        ]),
      ),
    )

    renderPage()

    expect(await screen.findByText('No integrations configured yet.')).toBeInTheDocument()
    await userEvent.setup().selectOptions(screen.getByText('Select…').closest('select')!, 'generic_ssh')

    expect(screen.queryByRole('spinbutton', { name: /Device/ })).not.toBeInTheDocument()
    const devicePicker = await screen.findByRole('combobox', { name: /Device/ })
    expect(within(devicePicker).getByText('pve1 (192.168.1.10)')).toBeInTheDocument()
    expect(within(devicePicker).getByText('— leave empty for a wallet credential —')).toBeInTheDocument()
  })

  it('prefills the config form from router state (Discovery "Configure as" link)', async () => {
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([DEMO_TYPE])),
      http.get('/api/credentials', () => HttpResponse.json([])),
      http.get('/api/integrations', () => HttpResponse.json([])),
    )

    renderPage([
      {
        pathname: '/integrations',
        state: { prefillIntegration: { type_key: 'demo', host: '10.0.0.5', port: 1234 } },
      },
    ])

    expect(await screen.findByText('No integrations configured yet.')).toBeInTheDocument()
    expect(await screen.findByRole('textbox', { name: /Host/ })).toHaveValue('10.0.0.5')
    expect(screen.getByRole('spinbutton', { name: /Port/ })).toHaveValue(1234)
  })
})
