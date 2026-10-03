/**
 * LabReportViewer
 * ---------------
 * Shows the original uploaded file (PDF or image) in a dialog. The file comes
 * from the same authenticated download endpoint, so only people who may
 * download it can see it; it is shown from a temporary blob URL that is
 * released when the dialog closes.
 */

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, FileWarning } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/misc'
import { apiErrorBody, labReportService } from '@/lib/api'
import { saveBlob } from '@/lib/utils'
import type { LabReport } from '@/lib/types'

const MIME: Record<string, string> = {
  PDF: 'application/pdf',
  PNG: 'image/png',
  JPG: 'image/jpeg',
  JPEG: 'image/jpeg',
}

export function LabReportViewer({ report, open, onOpenChange }: {
  report: LabReport
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const type = MIME[(report.file_type ?? '').toUpperCase()]
  const fileQ = useQuery({
    queryKey: ['report-file', report.id],   // not under 'lab', so list refreshes don't refetch it
    queryFn: () => labReportService.download(report.id),
    enabled: open,
    staleTime: Infinity,
    gcTime: 0,
  })

  // The server sends the file as a generic download; give it its real type so
  // the browser can display it.
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!open || !fileQ.data || !type) return
    const blobUrl = URL.createObjectURL(new Blob([fileQ.data], { type }))
    setUrl(blobUrl)
    return () => { URL.revokeObjectURL(blobUrl); setUrl(null) }
  }, [open, fileQ.data, type])

  const title = report.name || `Lab report ${report.id}`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[92vh] max-w-4xl flex-col">
        <DialogHeader>
          <DialogTitle className="truncate">{title}</DialogTitle>
          <DialogDescription>The original file you uploaded{report.file_type ? ` (${report.file_type})` : ''}.</DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-auto rounded-[var(--radius-md)] border border-border bg-surface-2">
          {fileQ.isLoading && <Skeleton className="h-[70vh] w-full" aria-label="Loading report" />}
          {(fileQ.isError || (!fileQ.isLoading && !type)) && (
            <div className="flex h-60 flex-col items-center justify-center gap-2 p-6 text-center text-sm text-muted-foreground" role="alert">
              <FileWarning className="size-6" />
              {fileQ.isError ? apiErrorBody(fileQ.error).message : 'This file type cannot be shown here. Download it instead.'}
            </div>
          )}
          {url && type === 'application/pdf' && (
            <iframe src={url} title={title} className="h-[70vh] w-full bg-white" />
          )}
          {url && type?.startsWith('image/') && (
            <img src={url} alt={title} className="mx-auto h-auto max-w-full bg-white" />
          )}
        </div>

        <DialogFooter>
          <Button variant="secondary" disabled={!fileQ.data}
            onClick={() => fileQ.data && saveBlob(fileQ.data, title)}>
            <Download className="size-4" />Download
          </Button>
          <DialogClose asChild><Button>Close</Button></DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
