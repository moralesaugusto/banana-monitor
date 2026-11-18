import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { KnowledgeBrowsePage } from './KnowledgeBrowsePage'

const settingsOn = { knowledge_base_enabled: true }
const settingsOff = { knowledge_base_enabled: false }

const notes = { id: 1, name: 'LAN notes', description: '', entry_count: 1, point_count: 3, total_chars: 400 }
const entry = {
  id: 10,
  title: 'Fail2ban',
  content_excerpt: 'SSH is protected by fail2ban after 5 attempts and a full paragraph more...',
  source: 'human',
  created_at: '2026-11-16T00:00:00Z',
  updated_at: '2026-11-16T00:00:00Z',
}
const fullEntry = {
  id: 10,
  collection_id: 1,
  title: 'Fail2ban',
  content: 'SSH is protected by fail2ban after 5 attempts and a full paragraph more than the excerpt shows.',
  source: 'human',
  embedding_model: 'nomic-embed-text',
  dims: 768,
  created_at: '2026-11-16T00:00:00Z',
  updated_at: '2026-11-16T00:00:00Z',
}

function renderPage(initialPath = '/') {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <KnowledgeBrowsePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('KnowledgeBrowsePage', () => {
  beforeEach(() => {
    queryClient.clear()
    server.use(
      http.get('/api/ai-mode/settings', () => HttpResponse.json(settingsOn)),
      http.get('/api/knowledge/collections', () => HttpResponse.json([notes])),
      http.get('/api/knowledge/collections/1/entries', () => HttpResponse.json([entry])),
    )
  })

  it('shows the off-state banner only when the knowledge base is switched off', async () => {
    server.use(http.get('/api/ai-mode/settings', () => HttpResponse.json(settingsOff)))
    renderPage()

    expect(await screen.findByText(/knowledge base is turned off/)).toBeInTheDocument()
  })

  it('shows no banner when the knowledge base is on, and lists the selected collection\'s entries', async () => {
    renderPage()

    expect(await screen.findByText('Fail2ban')).toBeInTheDocument()
    expect(screen.queryByText(/knowledge base is turned off/)).not.toBeInTheDocument()
  })

  it("shows each collection's vector and approximate token counts", async () => {
    renderPage()

    expect(await screen.findByText(/3 vectors/)).toBeInTheDocument()
    expect(screen.getByText(/~100 tokens/)).toBeInTheDocument() // 400 chars / 4
  })

  it('offers to load example entries for an empty Security knowledge collection, in the context of tajonaso', async () => {
    const secKnowledge = { id: 2, name: 'Security knowledge', description: '', entry_count: 0, point_count: 0, total_chars: 0 }
    const posted: Record<string, unknown>[] = []
    server.use(
      http.get('/api/knowledge/collections', () => HttpResponse.json([notes, secKnowledge])),
      http.get('/api/knowledge/collections/2/entries', () => HttpResponse.json([])),
      http.post('/api/knowledge/collections/2/entries', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        posted.push(body)
        return HttpResponse.json([{ ...entry, id: posted.length, title: body.title }], { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByText('Security knowledge'))
    await user.click(await screen.findByRole('button', { name: /Load example entries/ }))

    expect(posted.length).toBeGreaterThan(0)
    expect(posted.some((p) => String(p.content).toLowerCase().includes('tajonaso'))).toBe(true)
  })

  it('does not offer example entries once the collection already has content', async () => {
    renderPage()

    await screen.findByText('Fail2ban')
    expect(screen.queryByRole('button', { name: /Load example entries/ })).not.toBeInTheDocument()
  })

  it('shows an error instead of silently doing nothing when loading example entries fails', async () => {
    const secKnowledge = { id: 2, name: 'Security knowledge', description: '', entry_count: 0, point_count: 0, total_chars: 0 }
    server.use(
      http.get('/api/knowledge/collections', () => HttpResponse.json([notes, secKnowledge])),
      http.get('/api/knowledge/collections/2/entries', () => HttpResponse.json([])),
      http.post('/api/knowledge/collections/2/entries', () =>
        HttpResponse.json({ detail: "embedding request failed: model 'nomic-embed-text' not found" }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByText('Security knowledge'))
    await user.click(await screen.findByRole('button', { name: /Load example entries/ }))

    expect(await screen.findByText(/embedding request failed/)).toBeInTheDocument()
  })

  it("re-embeds a collection under the current settings", async () => {
    let reembedded = false
    server.use(
      http.post('/api/knowledge/collections/1/reembed', () => {
        reembedded = true
        return HttpResponse.json({ ...notes, point_count: 1 })
      }),
    )
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Fail2ban')

    await user.click(screen.getByRole('button', { name: 'Re-embed' }))

    expect(reembedded).toBe(true)
  })

  it('adds a new entry', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      http.post('/api/knowledge/collections/1/entries', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json([{ ...entry, id: 11, title: posted.title }], { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Fail2ban')

    await user.type(screen.getByPlaceholderText('Title'), 'New note')
    await user.type(screen.getByPlaceholderText(/Paste or write the text/), 'some content')
    await user.click(screen.getByRole('button', { name: 'Add entry' }))

    expect(posted).toMatchObject({ title: 'New note', content: 'some content' })
  })

  it('loads the full content (not the truncated excerpt) when editing', async () => {
    server.use(http.get('/api/knowledge/entries/10', () => HttpResponse.json(fullEntry)))
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Fail2ban')

    await user.click(screen.getByRole('button', { name: 'Edit' }))

    const textarea = await screen.findByDisplayValue(fullEntry.content)
    expect(textarea).toBeInTheDocument()
    expect(screen.queryByDisplayValue(entry.content_excerpt)).not.toBeInTheDocument()
  })

  it('shows the entry detail with embedding metadata when ?entry= is in the URL', async () => {
    server.use(http.get('/api/knowledge/entries/10', () => HttpResponse.json(fullEntry)))
    renderPage('/?entry=10')

    expect(await screen.findByText(fullEntry.content)).toBeInTheDocument()
    expect(screen.getByText('nomic-embed-text')).toBeInTheDocument()
    expect(screen.getByText('768')).toBeInTheDocument()
  })

  it('deletes an entry after confirming', async () => {
    let deleted = false
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.use(
      http.delete('/api/knowledge/entries/10', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Fail2ban')

    await user.click(screen.getByRole('button', { name: 'Delete' }))

    expect(deleted).toBe(true)
  })
})
