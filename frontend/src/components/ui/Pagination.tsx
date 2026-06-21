import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from './Button'

import type { PaginationMeta } from '../../types'

export type { PaginationMeta } from '../../types'

export const DEFAULT_PAGINATION_META: PaginationMeta = {
  total: 0,
  page: 1,
  limit: 25,
  pages: 1,
}

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const

interface PaginationProps {
  meta: PaginationMeta
  onPageChange: (page: number) => void
  onLimitChange: (limit: number) => void
  disabled?: boolean
}

export function Pagination({
  meta,
  onPageChange,
  onLimitChange,
  disabled = false,
}: PaginationProps) {
  const { page, pages, total, limit } = meta
  const canGoPrev = page > 1
  const canGoNext = page < pages

  if (total === 0) {
    return null
  }

  const rangeStart = (page - 1) * limit + 1
  const rangeEnd = Math.min(page * limit, total)

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-hairline px-1 pt-3">
      <p className="text-xs text-ink-mute-2">
        Showing {rangeStart}–{rangeEnd} of {total}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-xs text-ink-mute-2">
          Rows
          <select
            value={limit}
            disabled={disabled}
            onChange={(event) => onLimitChange(Number(event.target.value))}
            className="cursor-pointer rounded-sm border border-hairline-strong bg-canvas-night px-2 py-1 text-sm text-white focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          >
            {PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <span className="text-xs text-ink-mute-2">
          Page {page} of {pages}
        </span>
        <Button
          variant="secondary"
          disabled={disabled || !canGoPrev}
          onClick={() => onPageChange(page - 1)}
          aria-label="Previous page"
        >
          <ChevronLeft className="h-4 w-4" aria-hidden />
        </Button>
        <Button
          variant="secondary"
          disabled={disabled || !canGoNext}
          onClick={() => onPageChange(page + 1)}
          aria-label="Next page"
        >
          <ChevronRight className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    </div>
  )
}
