/**
 * ReportScan
 * ----------
 * The uploaded file itself (PDF or image), fetched through the authenticated
 * download endpoint and shown from a temporary blob URL, so values can be
 * checked against the scan.
 */
import { useEffect, useState } from 'react'
import { Skeleton } from '@/components/ui/misc'
import { labReportService } from '@/lib/api'

export function ReportScan({ id, type }: { id: number; type?: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let objectUrl: string | null = null
    labReportService.download(id)
      .then((blob) => {
        const mime = type === 'PDF' ? 'application/pdf' : type === 'PNG' ? 'image/png' : 'image/jpeg'
        objectUrl = URL.createObjectURL(new Blob([blob], { type: mime }))
        setUrl(objectUrl)
      })
      .catch(() => setFailed(true))
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [id, type])

  if (failed) return <p className="p-4 text-sm text-muted-foreground">The report file could not be shown.</p>
  if (!url) return <Skeleton className="h-[480px] w-full" />
  return type === 'PDF'
    ? <iframe src={url} title="Uploaded report" className="h-[560px] w-full rounded-[var(--radius-md)] border border-border bg-white" />
    : <img src={url} alt="Uploaded report" className="w-full rounded-[var(--radius-md)] border border-border bg-white" />
}
