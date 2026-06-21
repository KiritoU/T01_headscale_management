import type { ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { DataTable, type Column } from '../ui/DataTable'
import { Pagination, type PaginationMeta } from '../ui/Pagination'

interface MonitoringTableSectionProps<T> {
  title: string
  description: string
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  emptyMessage: string
  filteredEmptyMessage?: string
  meta: PaginationMeta
  onPageChange: (page: number) => void
  onLimitChange: (limit: number) => void
  filters?: ReactNode
  loading?: boolean
  hasActiveFilters?: boolean
}

export function MonitoringTableSection<T>({
  title,
  description,
  columns,
  rows,
  rowKey,
  emptyMessage,
  filteredEmptyMessage = 'No records match the current filters.',
  meta,
  onPageChange,
  onLimitChange,
  filters,
  loading = false,
  hasActiveFilters = false,
}: MonitoringTableSectionProps<T>) {
  const showFilteredEmpty = hasActiveFilters && meta.total === 0

  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-medium text-white">{title}</h3>
        <p className="text-xs text-ink-mute-2">{description}</p>
      </div>
      {filters ? (
        <div className="flex flex-wrap items-end gap-3 rounded-md border border-hairline bg-canvas-night-soft p-3">
          {filters}
        </div>
      ) : null}
      <div className="relative space-y-3">
        {loading ? (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-md bg-canvas-night/60">
            <Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden />
          </div>
        ) : null}
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={rowKey}
          emptyMessage={showFilteredEmpty ? filteredEmptyMessage : emptyMessage}
        />
        <Pagination
          meta={meta}
          onPageChange={onPageChange}
          onLimitChange={onLimitChange}
          disabled={loading}
        />
      </div>
    </section>
  )
}
