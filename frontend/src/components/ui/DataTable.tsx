import type { ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  className?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  emptyMessage?: string
  onRowClick?: (row: T) => void
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  emptyMessage = 'No records found.',
  onRowClick,
}: DataTableProps<T>) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-hairline bg-canvas-night-soft px-6 py-12 text-center text-sm text-ink-mute-2">
        {emptyMessage}
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-md border border-hairline">
      <table className="min-w-full divide-y divide-hairline text-left text-sm">
        <thead className="bg-canvas-night-soft">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`px-4 py-3 text-xs font-medium uppercase tracking-wide text-ink-mute-2 ${column.className ?? ''}`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-hairline bg-canvas-night">
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={
                onRowClick
                  ? 'cursor-pointer transition-colors hover:bg-white/[0.03]'
                  : undefined
              }
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`px-4 py-3 text-white ${column.className ?? ''}`}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
