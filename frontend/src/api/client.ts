export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** FastAPI error bodies are `{"detail": "..."}` (a plugin/route raising HTTPException with a plain
 * string) or `{"detail": [{"msg": "...", ...}, ...]}` (FastAPI's own request-validation 422s, before a
 * route body is even reached). Pulls out just the human-readable part of either shape; anything else
 * (a non-JSON body, an HTML error page) falls back to the raw text as-is. */
export function extractDetail(bodyText: string): string {
  try {
    const parsed = JSON.parse(bodyText) as { detail?: unknown } | null
    const detail = parsed?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          item && typeof item === 'object' && 'msg' in item
            ? String((item as { msg: unknown }).msg).replace(/^Value error, /, '')
            : JSON.stringify(item),
        )
        .join('; ')
    }
  } catch {
    // Not JSON - fall through to the raw text.
  }
  return bodyText
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })

  if (!response.ok) {
    const body = await response.text()
    throw new ApiError(response.status, extractDetail(body) || response.statusText)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
