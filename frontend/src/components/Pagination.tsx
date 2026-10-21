import type { usePaging } from '../lib/usePaging'

const PAGE_SIZES = [10, 25, 50, 100]

export function Pagination({
  total,
  start,
  pageSize,
  page,
  pages,
  setPage,
  setPageSize,
}: ReturnType<typeof usePaging>['footer']) {
  if (total === 0) return null
  const end = Math.min(start + pageSize, total)
  const numbers = Array.from({ length: pages }, (_, i) => i + 1).filter(
    (n) => n === 1 || n === pages || Math.abs(n - page) <= 1,
  )
  const button = 'h-8 min-w-8 rounded-control px-2 text-sm'
  return (
    <div className="flex flex-wrap items-center justify-end gap-3 px-4 py-3 text-sm text-fg-muted">
      <span>
        Showing {start + 1}-{end} of {total} records
      </span>
      <div className="flex items-center gap-1">
        <button type="button" aria-label="Previous page" disabled={page === 1} className={`${button} disabled:opacity-40`} onClick={() => setPage(page - 1)}>
          ‹
        </button>
        {numbers.map((n, i) => (
          <span key={n} className="flex items-center gap-1">
            {i > 0 && n - numbers[i - 1] > 1 && <span aria-hidden>…</span>}
            <button
              type="button"
              aria-current={n === page ? 'page' : undefined}
              className={`${button} ${n === page ? 'bg-accent-soft-strong font-medium text-accent-strong' : 'hover:bg-fg-subtle/10'}`}
              onClick={() => setPage(n)}
            >
              {n}
            </button>
          </span>
        ))}
        <button type="button" aria-label="Next page" disabled={page === pages} className={`${button} disabled:opacity-40`} onClick={() => setPage(page + 1)}>
          ›
        </button>
      </div>
      <select
        aria-label="Rows per page"
        className="rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg"
        value={pageSize}
        onChange={(e) => {
          setPageSize(Number(e.target.value))
          setPage(1)
        }}
      >
        {PAGE_SIZES.map((size) => (
          <option key={size} value={size}>
            {size} /page
          </option>
        ))}
      </select>
    </div>
  )
}
