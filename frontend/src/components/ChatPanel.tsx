import { useState } from 'react'
import Markdown from 'react-markdown'
import { Link } from 'react-router-dom'
import { useAssistantMessages, useClearAssistantMessages, useSendChatMessage } from '../api/assistant'
import { Badge } from './Badge'
import { Card } from './Card'
import { ChatIcon, CloseIcon, SettingsIcon } from './icons'

const inputClasses =
  'rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'

function ToolCallChip({ name, arguments: args }: { name: string; arguments: Record<string, unknown> }) {
  const argSummary = Object.entries(args)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(', ')
  return (
    <Badge tone="info">
      → {name}
      {argSummary ? ` (${argSummary})` : ''}
    </Badge>
  )
}

/** Global chat assistant: a floating launcher + slide-in drawer, mounted once in AppShell so it's available on every route. */
export function ChatPanel() {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')

  const { data: messages, isLoading } = useAssistantMessages()
  const sendMessage = useSendChatMessage()
  const clearMessages = useClearAssistantMessages()

  function handleSend() {
    const text = draft.trim()
    if (!text || sendMessage.isPending) return
    setDraft('')
    sendMessage.mutate(text)
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 flex h-12 w-12 items-center justify-center rounded-full bg-accent text-on-accent shadow-lg hover:brightness-95"
        title="Open assistant"
      >
        <ChatIcon className="h-5 w-5" />
      </button>
    )
  }

  return (
    <aside className="fixed bottom-0 right-0 top-0 z-40 flex w-96 max-w-full flex-col border-l border-line bg-surface shadow-xl">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="text-sm font-semibold text-fg">Assistant</span>
        <div className="flex items-center gap-1">
          <Link
            to="/ai/config?tab=assistant"
            onClick={() => setOpen(false)}
            className="rounded-control p-1.5 text-fg-muted hover:bg-accent-soft hover:text-fg"
            title="Assistant settings"
          >
            <SettingsIcon className="h-4 w-4" />
          </Link>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-control p-1.5 text-fg-muted hover:bg-accent-soft hover:text-fg"
            title="Close"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {isLoading && <p className="text-sm text-fg-muted">Loading…</p>}
        {!isLoading && messages?.length === 0 && (
          <p className="text-sm text-fg-muted">
            Ask about your devices, services, or alerts - or ask it to accept a discovery candidate, create
            a service, or trigger a scan.
          </p>
        )}
        <div className="flex flex-col gap-3">
          {messages?.map((message) => (
            <Card
              key={message.id}
              className={`px-3 py-2 text-sm ${message.role === 'user' ? 'ml-6 bg-accent-soft' : 'mr-6'}`}
            >
              <div className="prose-sm text-fg [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4">
                <Markdown>{message.content}</Markdown>
              </div>
              {message.tool_calls && message.tool_calls.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {message.tool_calls.map((call, i) => (
                    <ToolCallChip key={i} name={call.name} arguments={call.arguments} />
                  ))}
                </div>
              )}
            </Card>
          ))}
          {sendMessage.isPending && <p className="text-xs text-fg-muted">Thinking…</p>}
          {sendMessage.isError && <p className="text-xs text-red-600">Failed to reach the assistant.</p>}
        </div>
      </div>

      <div className="border-t border-line p-3">
        <div className="flex items-center gap-2">
          <input
            className={`${inputClasses} flex-1`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSend()
            }}
            placeholder="Ask the assistant…"
          />
          <button
            type="button"
            className="rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent hover:brightness-95 disabled:opacity-50"
            onClick={handleSend}
            disabled={sendMessage.isPending}
          >
            Send
          </button>
        </div>
        <button
          type="button"
          className="mt-2 text-xs text-fg-muted hover:underline"
          onClick={() => clearMessages.mutate()}
        >
          Clear conversation
        </button>
      </div>
    </aside>
  )
}
