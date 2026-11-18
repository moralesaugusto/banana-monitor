import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { KnowledgeSettingsPage } from './KnowledgeSettingsPage'

const settings = {
  enabled: false,
  system_prompt: '',
  model_override: '',
  llm_base_url: 'http://agents/v1',
  llm_model: 'agent-m',
  llm_provider: 'ollama',
  llm_credential_id: null,
  llm_call_timeout_seconds: 120,
  max_iterations: 15,
  temperature: 0.2,
  max_targets: 25,
  enabled_tools: [],
  allow_undefined_network_scan: false,
  undefined_scan_max_hosts: 256,
  ollama_max_concurrent_calls: 2,
  openrouter_max_concurrent_calls: 4,
  memory_max_entries_per_agent: 30,
  memory_max_content_chars: 500,
  memory_max_inject_chars: 2000,
  knowledge_base_enabled: false,
  knowledge_embedding_base_url: '',
  knowledge_embedding_model: 'nomic-embed-text',
  knowledge_embedding_credential_id: null,
}

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <KnowledgeSettingsPage />
    </QueryClientProvider>,
  )
}

describe('KnowledgeSettingsPage', () => {
  beforeEach(() => {
    queryClient.clear()
    server.use(http.get('/api/ai-mode/settings', () => HttpResponse.json(settings)))
  })

  it('shows the current off state and explains what the switch controls', async () => {
    renderPage()

    const checkbox = await screen.findByRole('checkbox', { name: 'Turn the knowledge base on' })
    expect(checkbox).not.toBeChecked()
    expect(screen.getByText(/search_knowledge and add_knowledge_entry are refused/)).toBeInTheDocument()
  })

  it('turns the switch on and saves it', async () => {
    let sent: Record<string, unknown> | null = null
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...sent })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const checkbox = await screen.findByRole('checkbox', { name: 'Turn the knowledge base on' })
    await user.click(checkbox)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(sent).toMatchObject({ knowledge_base_enabled: true })
  })

  it('only sends the three knowledge fields, never the rest of AiModeSettings', async () => {
    let sent: Record<string, unknown> | null = null
    server.use(
      http.put('/api/ai-mode/settings', async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...sent })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const checkbox = await screen.findByRole('checkbox', { name: 'Turn the knowledge base on' })
    await user.click(checkbox)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await screen.findByText('Saved.')
    // A save from here must never carry fields another tab could have changed in the meantime
    // (max_iterations, enabled_tools, llm_model, ...) - only these three belong to this page.
    expect(Object.keys(sent ?? {}).sort()).toEqual(
      [
        'knowledge_base_enabled',
        'knowledge_embedding_base_url',
        'knowledge_embedding_model',
        'knowledge_embedding_credential_id',
      ].sort(),
    )
  })

  it('picks an already-stored API key for the embedding host, so calls can carry an Authorization header', async () => {
    let sent: Record<string, unknown> | null = null
    server.use(
      http.get('/api/credentials', () =>
        HttpResponse.json([
          {
            id: 5,
            label: 'self-hosted embeddings key',
            credential_type: 'api_token',
            created_at: '',
            rotated_at: null,
            last_used_at: null,
            used_by: [],
          },
        ]),
      ),
      http.put('/api/ai-mode/settings', async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...sent })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.selectOptions(await screen.findByLabelText('Embedding host API key'), '5')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await screen.findByText('Saved.')
    expect(sent).toMatchObject({ knowledge_embedding_credential_id: 5 })
  })

  it('resets the knowledge base after confirming, wiping every collection\'s entries', async () => {
    let resetCalled = false
    server.use(
      http.post('/api/knowledge/reset', () => {
        resetCalled = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Reset the knowledge base' }))

    expect(resetCalled).toBe(true)
  })
})
