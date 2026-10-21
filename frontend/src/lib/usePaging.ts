import { useState } from 'react'

/** Client-side paging: the rows for the current page plus the state the footer needs. */
export function usePaging<T>(rows: T[]) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const pages = Math.max(1, Math.ceil(rows.length / pageSize))
  const current = Math.min(page, pages)
  const start = (current - 1) * pageSize
  return {
    rows: rows.slice(start, start + pageSize),
    footer: { total: rows.length, start, pageSize, page: current, pages, setPage, setPageSize },
  }
}
