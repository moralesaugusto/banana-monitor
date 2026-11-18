import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAiModeSettings } from '../../api/aiMode'
import {
  useAddEntry,
  useCreateCollection,
  useDeleteAllEntries,
  useDeleteCollection,
  useDeleteEntry,
  useEditEntry,
  useKnowledgeCollections,
  useKnowledgeEntries,
  useKnowledgeEntry,
  useReembedCollection,
  type KnowledgeEntrySummary,
} from '../../api/knowledge'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'
import { charsToApproxTokens } from './agentFields'

const primaryButtonClasses =
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'
const ghostButtonClasses =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-50'
const inputClasses = 'mt-1 w-full rounded-control border border-line bg-surface px-2 py-1 text-sm'
/** Must match EntryUpdate.content's cap (schemas/knowledge.py) - editing never re-chunks. */
const EDIT_CONTENT_MAX_CHARS = 500

function NewCollectionForm({ onCreated }: { onCreated: (id: number) => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const create = useCreateCollection()

  if (!open) {
    return (
      <button type="button" className={ghostButtonClasses} onClick={() => setOpen(true)}>
        New collection
      </button>
    )
  }
  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        create.mutate({ name }, { onSuccess: (c) => { onCreated(c.id); setOpen(false); setName('') } })
      }}
    >
      <input
        autoFocus
        className={inputClasses}
        placeholder="Collection name"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <button type="submit" className={primaryButtonClasses} disabled={create.isPending || !name.trim()}>
        Create
      </button>
      <button type="button" className={ghostButtonClasses} onClick={() => setOpen(false)}>
        Cancel
      </button>
    </form>
  )
}

/** Two realistic Tajonaso-style findings (see backend/app/agents_system_prompts/tajonaso.md),
 * so a brand new install's Knowledge Map isn't an empty page the first time you look at it, and
 * so the example is grounded in an agent this app actually ships rather than invented content.
 * Tajonaso's own instructions already cover both outcomes a real run produces: something found,
 * and a clean check that still counts as a useful result - these mirror that exactly. */
const TAJONASO_EXAMPLE_ENTRIES = [
  {
    title: 'SSH password auth left enabled (10.0.0.50)',
    content:
      'Findings: nmap_scan against 10.0.0.50 found SSH (port 22, OpenSSH 8.9) and HTTP (port 80) open.\n\n' +
      'Issues: the SSH server accepts password authentication (confirmed via its banner and a connection ' +
      'attempt) with no visible rate limiting or lockout after repeated failed attempts. A credential attack ' +
      "against a small list of common usernames found no working password, but the exposure itself - a LAN " +
      'host reachable with password auth and no lockout - is worth tightening: key-based auth only, or ' +
      'fail2ban-style lockout, would close it.\n\nThis note was written by tajonaso, Banana\'s offensive-security agent.',
  },
  {
    title: 'Credential attack attempted, no weak password found (10.0.0.12)',
    content:
      'Findings: nmap_scan against 10.0.0.12 found only SSH (port 22) open, OpenSSH 9.3.\n\n' +
      'Issues: a credential attack was attempted against the admin/root accounts using a short common-password ' +
      'list. No weak credential was found. This is a valid, useful result on its own: the host was actually ' +
      'tested, not skipped, and came back clean - not every investigation should end in a finding.\n\n' +
      "This note was written by tajonaso, Banana's offensive-security agent.",
  },
]

function ExampleEntriesOffer({ collectionId }: { collectionId: number }) {
  const add = useAddEntry(collectionId)
  return (
    <div className="p-4">
      <p className="text-sm text-fg-muted">No entries yet.</p>
      <p className="mt-1 text-xs text-fg-muted">
        Want to see what this looks like with real content? Load two example findings written the way
        Tajonaso, this app's offensive-security agent, actually reports them.
      </p>
      <button
        type="button"
        className={ghostButtonClasses + ' mt-2'}
        disabled={add.isPending}
        onClick={() => TAJONASO_EXAMPLE_ENTRIES.forEach((e) => add.mutate(e))}
      >
        {add.isPending ? 'Loading…' : 'Load example entries (Tajonaso)'}
      </button>
      {add.isError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{add.error.message}</p>}
    </div>
  )
}

function AddEntryForm({ collectionId }: { collectionId: number }) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const add = useAddEntry(collectionId)

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        add.mutate({ title, content }, { onSuccess: () => { setTitle(''); setContent('') } })
      }}
    >
      <input className={inputClasses} placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea
        className={`${inputClasses} h-24`}
        placeholder="Paste or write the text to remember. Long text is split into several smaller pieces automatically."
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      <div className="flex items-center gap-2">
        <button type="submit" className={primaryButtonClasses} disabled={add.isPending || !title.trim() || !content.trim()}>
          {add.isPending ? 'Adding…' : 'Add entry'}
        </button>
        {add.isError && <span className="text-sm text-red-600 dark:text-red-400">{add.error.message}</span>}
      </div>
    </form>
  )
}

/** The form itself, mounted only once the full entry has actually loaded - so its local
 * title/content state is seeded correctly on its very first render, with no effect needed to
 * re-sync it after the fact. */
function EditEntryFormLoaded({
  entryId,
  initialTitle,
  initialContent,
  onDone,
}: {
  entryId: number
  initialTitle: string
  initialContent: string
  onDone: () => void
}) {
  const [title, setTitle] = useState(initialTitle)
  const [content, setContent] = useState(initialContent)
  const edit = useEditEntry()

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        edit.mutate({ id: entryId, title, content }, { onSuccess: onDone })
      }}
    >
      <input className={inputClasses} value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea
        className={`${inputClasses} h-24`}
        value={content}
        maxLength={EDIT_CONTENT_MAX_CHARS}
        onChange={(e) => setContent(e.target.value)}
      />
      <p className="text-xs text-fg-subtle">
        {content.length}/{EDIT_CONTENT_MAX_CHARS} characters - editing keeps this as one piece and never
        re-splits it. For longer text, delete this entry and add the new text instead.
      </p>
      <div className="flex items-center gap-2">
        <button type="submit" className={primaryButtonClasses} disabled={edit.isPending}>
          Save
        </button>
        <button type="button" className={ghostButtonClasses} onClick={onDone}>
          Cancel
        </button>
        {edit.isError && <span className="text-sm text-red-600 dark:text-red-400">{edit.error.message}</span>}
      </div>
    </form>
  )
}

/** The edit form loads the entry's *full* content itself (never the list's truncated excerpt) -
 * editing from the excerpt would silently cut off and overwrite anything past it. */
function EditEntryForm({ entryId, onDone }: { entryId: number; onDone: () => void }) {
  const { data: full } = useKnowledgeEntry(entryId)

  return (
    <li className="border-b border-line p-3 last:border-b-0">
      {!full ? (
        <p className="text-sm text-fg-muted">Loading…</p>
      ) : (
        <EditEntryFormLoaded
          key={full.id}
          entryId={entryId}
          initialTitle={full.title}
          initialContent={full.content}
          onDone={onDone}
        />
      )}
    </li>
  )
}

function EntryRow({ entry, collectionId }: { entry: KnowledgeEntrySummary; collectionId: number }) {
  const [editing, setEditing] = useState(false)
  const remove = useDeleteEntry(collectionId)

  if (editing) {
    return <EditEntryForm entryId={entry.id} onDone={() => setEditing(false)} />
  }
  return (
    <li className="flex items-start justify-between gap-3 border-b border-line p-3 last:border-b-0">
      <div className="min-w-0">
        <div className="text-sm font-medium text-fg">{entry.title}</div>
        <div className="mt-0.5 text-sm text-fg-muted">{entry.content_excerpt}</div>
        <div className="mt-1 text-xs text-fg-subtle">{new Date(entry.created_at).toLocaleString()}</div>
      </div>
      <div className="flex shrink-0 gap-2">
        <button type="button" className={ghostButtonClasses} onClick={() => setEditing(true)}>
          Edit
        </button>
        <button
          type="button"
          className="rounded-control border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
          disabled={remove.isPending}
          onClick={() => window.confirm(`Delete "${entry.title}"?`) && remove.mutate(entry.id)}
        >
          Delete
        </button>
      </div>
    </li>
  )
}

/** The detail view a Knowledge Map click lands on (`?entry=<id>`): full content plus the
 * embedding metadata no other page shows, so a model/dimension mismatch (docs/decisions.md) is
 * something you can actually go look at. */
function EntryDetail({ entryId, onClose }: { entryId: number; onClose: () => void }) {
  const { data: entry } = useKnowledgeEntry(entryId)
  if (!entry) return null
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-sm font-semibold text-fg">{entry.title}</h2>
        <button type="button" className="text-xs text-fg-muted hover:underline" onClick={onClose}>
          Close
        </button>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm text-fg-muted">{entry.content}</p>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-fg-subtle sm:grid-cols-4">
        <div>
          <dt className="font-medium">Embedding model</dt>
          <dd>{entry.embedding_model || 'unknown'}</dd>
        </div>
        <div>
          <dt className="font-medium">Dimensions</dt>
          <dd>{entry.dims}</dd>
        </div>
        <div>
          <dt className="font-medium">Source</dt>
          <dd>{entry.source}</dd>
        </div>
        <div>
          <dt className="font-medium">Updated</dt>
          <dd>{new Date(entry.updated_at).toLocaleString()}</dd>
        </div>
      </dl>
    </Card>
  )
}

/** Browse, add, edit, delete and bulk-prune the knowledge base's collections and entries. Stays
 * reachable by direct URL even while the knowledge base is switched off - a banner says so. The
 * sidebar itself hides this link (and Map/Learn) while off, keeping only Knowledge > Settings,
 * since there is nothing useful to browse yet (see Sidebar.tsx's navGroups). */
export function KnowledgeBrowsePage() {
  const { data: aiSettings } = useAiModeSettings()
  const { data: collections, isLoading } = useKnowledgeCollections()
  const [searchParams, setSearchParams] = useSearchParams()
  const detailEntryId = Number(searchParams.get('entry')) || null
  const { data: detailEntry } = useKnowledgeEntry(detailEntryId)
  const [selected, setSelected] = useState<number | null>(null)
  const current = selected ?? detailEntry?.collection_id ?? collections?.[0]?.id ?? null
  const { data: entries } = useKnowledgeEntries(current)
  const deleteCollection = useDeleteCollection()
  const deleteAll = useDeleteAllEntries(current ?? 0)
  const reembed = useReembedCollection()

  return (
    <div>
      <PageHeader
        title="Knowledge"
        description="Collections group related notes; each one you add becomes a piece of text an agent can find later by meaning, not just by exact words."
      />
      {aiSettings && !aiSettings.knowledge_base_enabled && (
        <p className="mt-4 rounded-control border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          The knowledge base is turned off, so no agent can search or add to it yet. You can still browse and
          edit it here. Turn it on under Knowledge &gt; Settings.
        </p>
      )}

      {detailEntryId !== null && (
        <div className="mt-6">
          <EntryDetail entryId={detailEntryId} onClose={() => setSearchParams({})} />
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[16rem_1fr]">
        <Card className="self-start overflow-hidden">
          {isLoading && <p className="p-4 text-sm text-fg-muted">Loading…</p>}
          <ul>
            {collections?.map((c) => (
              <li key={c.id} className="border-b border-line last:border-b-0">
                <button
                  type="button"
                  className={`flex w-full flex-col gap-0.5 px-4 py-2.5 text-left hover:bg-accent-soft/60 ${c.id === current ? 'bg-accent-soft' : ''}`}
                  onClick={() => setSelected(c.id)}
                >
                  <span className="flex w-full items-center justify-between">
                    <span className="text-sm font-medium text-fg">{c.name}</span>
                    <span className="text-xs text-fg-subtle">{c.entry_count}</span>
                  </span>
                  <span className="text-xs text-fg-subtle">
                    {c.point_count} vector{c.point_count === 1 ? '' : 's'} · ~{charsToApproxTokens(c.total_chars)} tokens
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="p-3">
            <NewCollectionForm onCreated={setSelected} />
          </div>
        </Card>

        {current !== null && (
          <div className="flex flex-col gap-4">
            <Card className="p-4">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Add an entry</h2>
              <div className="mt-3">
                <AddEntryForm collectionId={current} />
              </div>
            </Card>

            <Card className="overflow-hidden">
              <div className="flex items-center justify-between p-3">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
                  Entries {entries && `(${entries.length})`}
                </h2>
                <div className="flex gap-2">
                  {entries && entries.length > 0 && (
                    <button
                      type="button"
                      className="text-xs font-medium text-fg-muted hover:underline disabled:opacity-50"
                      title="Re-embeds every entry under the current embedding settings (Knowledge > Settings) - fixes a model mismatch after changing the embedding host/model."
                      disabled={reembed.isPending}
                      onClick={() => reembed.mutate(current)}
                    >
                      {reembed.isPending ? 'Re-embedding…' : 'Re-embed'}
                    </button>
                  )}
                  {entries && entries.length > 0 && (
                    <button
                      type="button"
                      className="text-xs font-medium text-red-600 hover:underline"
                      onClick={() =>
                        window.confirm(`Delete all ${entries.length} entries in this collection?`) &&
                        deleteAll.mutate()
                      }
                    >
                      Delete all
                    </button>
                  )}
                  <button
                    type="button"
                    className="text-xs font-medium text-red-600 hover:underline"
                    onClick={() =>
                      window.confirm('Delete this collection and every entry in it?') &&
                      deleteCollection.mutate(current, { onSuccess: () => setSelected(null) })
                    }
                  >
                    Delete collection
                  </button>
                </div>
              </div>
              {entries?.length === 0 &&
                (collections?.find((c) => c.id === current)?.name === 'Security knowledge' ? (
                  <ExampleEntriesOffer collectionId={current} />
                ) : (
                  <p className="p-4 text-sm text-fg-muted">No entries yet.</p>
                ))}
              <ul>
                {entries?.map((entry) => <EntryRow key={entry.id} entry={entry} collectionId={current} />)}
              </ul>
            </Card>
          </div>
        )}
      </div>
    </div>
  )
}
