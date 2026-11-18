import { useState } from 'react'
import { type AiModeSettings, useAiModeSettings, useUpdateAiModeSettings } from '../../api/aiMode'
import { useCreateCredential } from '../../api/credentials'
import { useResetKnowledgeBase } from '../../api/knowledge'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'
import { SaveBar } from '../../components/SaveBar'
import { OpenRouterKeyPicker } from './OpenRouterKeyPicker'

const inputClasses = 'mt-1 w-full rounded-control border border-line bg-surface px-2 py-1 text-sm'

type KnowledgeFields = Pick<
  AiModeSettings,
  | 'knowledge_base_enabled'
  | 'knowledge_embedding_base_url'
  | 'knowledge_embedding_model'
  | 'knowledge_embedding_credential_id'
>

/** The form itself, mounted only once settings have actually loaded - so its local state is
 * narrowed to exactly these three fields from the start, and a save can never pick up the rest of
 * AiModeSettings (max_iterations, enabled_tools, ...) the way spreading the full `settings` object
 * into `draft` on the first edit used to: that could silently overwrite a change another tab made
 * to an unrelated field between this page loading and this page saving. */
function KnowledgeSettingsForm({
  initial,
  update,
}: {
  initial: KnowledgeFields
  update: ReturnType<typeof useUpdateAiModeSettings>
}) {
  const [draft, setDraft] = useState<KnowledgeFields>(initial)
  const [apiKey, setApiKey] = useState('')
  const createCredential = useCreateCredential()
  const reset = useResetKnowledgeBase()

  const set = <K extends keyof KnowledgeFields>(key: K, value: KnowledgeFields[K]) => {
    update.reset()
    setDraft((d) => ({ ...d, [key]: value }))
  }

  async function save() {
    let credentialId = draft.knowledge_embedding_credential_id
    if (apiKey) {
      const credential = await createCredential.mutateAsync({
        label: 'Embedding host API key',
        credential_type: 'api_token',
        secret: { token: apiKey },
      })
      credentialId = credential.id
      setDraft((d) => ({ ...d, knowledge_embedding_credential_id: credentialId }))
      setApiKey('')
    }
    update.mutate({ ...draft, knowledge_embedding_credential_id: credentialId })
  }

  return (
    <div>
      <PageHeader
        title="Knowledge settings"
        description="The master switch for the agent knowledge base, and where its embeddings come from."
      />
      <form
        className="mt-6"
        onSubmit={(e) => {
          e.preventDefault()
          void save()
        }}
      >
        <Card className="p-4">
          <SaveBar
            title="Knowledge base"
            description="Off by default. While off, search_knowledge and add_knowledge_entry are refused for every agent, whatever their own Tools list says - this is the one switch that controls both."
            saving={update.isPending}
            saved={update.isSuccess}
            error={update.isError ? update.error.message : null}
          />
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.knowledge_base_enabled}
              onChange={(e) => set('knowledge_base_enabled', e.target.checked)}
            />
            Turn the knowledge base on
          </label>
        </Card>

        <Card className="mt-4 p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Embeddings</h2>
          <p className="mt-1 text-xs text-fg-muted">
            Every piece of text saved or searched is converted to a vector by this model, called the same way
            as the chat model (an OpenAI-compatible <code>/embeddings</code> endpoint) - typically a small,
            dedicated embedding model on the same Ollama host, not the chat model itself.
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              Embedding host (optional)
              <input
                type="text"
                placeholder="Leave blank to use the agents' default Ollama host"
                className={inputClasses}
                value={draft.knowledge_embedding_base_url}
                onChange={(e) => set('knowledge_embedding_base_url', e.target.value)}
              />
            </label>
            <label className="text-sm">
              Embedding model
              <input
                type="text"
                className={inputClasses}
                value={draft.knowledge_embedding_model}
                onChange={(e) => set('knowledge_embedding_model', e.target.value)}
              />
            </label>
            <label className="text-sm sm:col-span-2">
              API key for the embedding host (optional)
              <OpenRouterKeyPicker
                inputClasses={inputClasses}
                credentialId={draft.knowledge_embedding_credential_id}
                onSelectCredential={(id) => set('knowledge_embedding_credential_id', id)}
                apiKey={apiKey}
                onChangeApiKey={setApiKey}
                matchLabel=""
                ariaLabel="Embedding host API key"
              />
              <span className="mt-1 block text-xs text-fg-muted">
                Only needed when the embedding host itself requires one (a local Ollama host usually doesn't).
                Pick an already-stored key, or paste a new one.
              </span>
            </label>
          </div>
        </Card>
      </form>

      <Card className="mt-4 p-4">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Danger zone</h2>
        <p className="mt-1 text-xs text-fg-muted">
          Deletes every entry and vector in every collection, so the knowledge base can start from scratch. The
          collections themselves are kept - only their contents are wiped. This cannot be undone.
        </p>
        <button
          type="button"
          className="mt-3 rounded-control border border-red-300 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:hover:bg-red-950"
          disabled={reset.isPending}
          onClick={() => {
            if (window.confirm('Delete every entry and vector in every collection? This cannot be undone.')) {
              reset.mutate()
            }
          }}
        >
          Reset the knowledge base
        </button>
        {reset.isSuccess && <p className="mt-2 text-xs text-fg-muted">Done - every collection is now empty.</p>}
        {reset.isError && (
          <p className="mt-2 text-xs text-red-600 dark:text-red-400">{reset.error.message}</p>
        )}
      </Card>
    </div>
  )
}

/** Gates on settings actually having loaded, so KnowledgeSettingsForm's local state can be seeded
 * directly from them with no effect needed to re-sync it after the fact. */
export function KnowledgeSettingsPage() {
  const { data: settings } = useAiModeSettings()
  const update = useUpdateAiModeSettings()
  if (!settings) return null
  // Picked explicitly, not just typed as KnowledgeFields: TypeScript's structural typing would
  // otherwise let the full AiModeSettings object through at runtime despite the narrower
  // annotation, which is exactly how this page used to leak every other field into a save.
  const initial: KnowledgeFields = {
    knowledge_base_enabled: settings.knowledge_base_enabled,
    knowledge_embedding_base_url: settings.knowledge_embedding_base_url,
    knowledge_embedding_model: settings.knowledge_embedding_model,
    knowledge_embedding_credential_id: settings.knowledge_embedding_credential_id,
  }
  return <KnowledgeSettingsForm key={JSON.stringify(initial)} initial={initial} update={update} />
}
