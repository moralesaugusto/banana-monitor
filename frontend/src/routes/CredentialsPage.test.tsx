import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Credential } from '../api/credentials'
import type { IntegrationTypeInfo } from '../api/integrations'
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
    used_by: ['integration pve1'],
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

  it('shows what a credential is used by, or that it is unused', async () => {
    const unused: Credential = { ...CREDENTIALS[0], id: 2, label: 'old-key', used_by: [] }
    server.use(http.get('/api/credentials', () => HttpResponse.json([CREDENTIALS[0], unused])))
    renderPage()

    expect(await screen.findByText('integration pve1')).toBeInTheDocument()
    expect(screen.getByText('Unused - safe to delete')).toBeInTheDocument()
  })

  it('renames a credential without touching its secret', async () => {
    let patched: Record<string, unknown> | null = null
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([])),
      http.get('/api/credentials', () => HttpResponse.json(CREDENTIALS)),
      http.patch('/api/credentials/1', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...CREDENTIALS[0], ...patched })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Edit/ }))
    const label = screen.getByRole('textbox', { name: 'Label' })
    await user.clear(label)
    await user.type(label, 'renamed')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(patched).toEqual({ label: 'renamed', in_agent_pool: false }))
  })

  it('adds a credential using custom JSON and replaces a secret', async () => {
    const TYPE: IntegrationTypeInfo = {
      type_key: 'proxmox',
      display_name: 'Proxmox VE',
      config_schema: { type: 'object', properties: {} },
      credential_schema: {
        type: 'object',
        properties: { token_id: { type: 'string', title: 'Token Id' }, token_secret: { type: 'string', title: 'Token Secret' } },
        required: ['token_id', 'token_secret'],
      },
    }
    let created: Record<string, unknown> | null = null
    let patched: Record<string, unknown> | null = null
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([TYPE])),
      http.get('/api/credentials', () => HttpResponse.json(CREDENTIALS)),
      http.post('/api/credentials', async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...CREDENTIALS[0], id: 2 }, { status: 201 })
      }),
      http.patch('/api/credentials/1', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(CREDENTIALS[0])
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'New credential' }))
    await user.type(screen.getByRole('textbox', { name: 'Label' }), 'extra')
    const secret = screen.getByRole('textbox', { name: /Secret/ })
    await user.clear(secret)
    await user.click(secret)
    await user.paste('{"token": "abc"}')
    await user.click(screen.getByRole('button', { name: 'Add credential' }))
    await waitFor(() => expect(created).toEqual({
        label: 'extra',
        credential_type: 'api_token',
        secret: { token: 'abc' },
        in_agent_pool: false,
      }))

    await user.click(await screen.findByRole('button', { name: /Edit/ }))
    await user.click(screen.getByRole('button', { name: 'Replace secret' }))
    await user.type(await screen.findByLabelText(/Token Id/), 'user@pam!t')
    await user.type(screen.getByLabelText(/Token Secret/), 'sekret')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(patched).toMatchObject({ secret: { token_id: 'user@pam!t', token_secret: 'sekret' } }))
  })

  it('offers a single API key field when replacing the secret of an AI agent key', async () => {
    const llmKey: Credential = { ...CREDENTIALS[0], id: 3, label: 'openrouter', used_by: ['the agents\' default LLM'] }
    let patched: Record<string, unknown> | null = null
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([])),
      http.get('/api/credentials', () => HttpResponse.json([llmKey])),
      http.patch('/api/credentials/3', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(llmKey)
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Edit/ }))
    await user.click(screen.getByRole('button', { name: 'Replace secret' }))
    await user.type(await screen.findByLabelText('API key'), 'sk-or-new')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(patched).toMatchObject({ secret: { token: 'sk-or-new' } }))
  })

  it('marks pooled credentials and adds one to the agent pool', async () => {
    let created: Record<string, unknown> | null = null
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([])),
      http.get('/api/credentials', () => HttpResponse.json([{ ...CREDENTIALS[0], in_agent_pool: true }])),
      http.post('/api/credentials', async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...CREDENTIALS[0], id: 9 }, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('In agent pool')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'New credential' }))
    const pool = screen.getByLabelText(/Include in the agents' credential pool/)
    expect(pool).not.toBeChecked()
    await user.type(screen.getByRole('textbox', { name: 'Label' }), 'fresh')
    await user.click(pool)
    const secret = screen.getByRole('textbox', { name: /Secret/ })
    await user.clear(secret)
    await user.click(secret)
    await user.paste('{"token": "t"}')
    await user.click(screen.getByRole('button', { name: 'Add credential' }))

    await waitFor(() => expect(created).toMatchObject({ label: 'fresh', in_agent_pool: true }))
  })
})

