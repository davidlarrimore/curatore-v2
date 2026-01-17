import { FileInfo } from '@/types'

function formatJobDate(date: Date): string {
  return new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(date)
}

export function getDefaultJobName(files: FileInfo[], createdAt: Date = new Date()): string {
  if (files.length === 1) {
    return files[0]?.filename || 'Untitled document'
  }

  const dateLabel = formatJobDate(createdAt)
  return `Batch ${files.length} files - ${dateLabel}`
}
