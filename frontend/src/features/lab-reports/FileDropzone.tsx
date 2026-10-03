import { useRef, useState } from 'react'
import { FileText, UploadCloud, X } from 'lucide-react'
import { formatBytes } from '@/lib/utils'
import { checkFile } from './file-check'

/** Drag-and-drop or click/keyboard to choose one report file. */
export function FileDropzone({
  file, onFile, disabled,
}: { file: File | null; onFile: (file: File | null, error: string | null) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function choose(f: File | undefined | null) {
    if (!f) return
    onFile(f, checkFile(f))
  }

  return (
    <div className="space-y-2">
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-describedby="dropzone-hint"
        onClick={() => !disabled && input.current?.click()}
        onKeyDown={(e) => {
          if (!disabled && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); input.current?.click() }
        }}
        onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); if (!disabled) choose(e.dataTransfer.files?.[0]) }}
        className={`flex cursor-pointer flex-col items-center gap-2 rounded-[var(--radius-lg)] border-2 border-dashed px-6 py-10 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
          dragging ? 'border-primary bg-primary-soft/40' : 'border-border hover:border-primary/60 hover:bg-surface-2'
        } ${disabled ? 'pointer-events-none opacity-60' : ''}`}
      >
        <UploadCloud className="size-8 text-primary" aria-hidden="true" />
        <p className="text-sm font-medium">Drag your lab report here, or click to choose a file</p>
        <p id="dropzone-hint" className="text-xs text-muted-foreground">PDF, PNG or JPG · up to 10 MB</p>
        <input
          ref={input}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          className="sr-only"
          aria-label="Lab report file"
          data-testid="file-input"
          onChange={(e) => { choose(e.target.files?.[0]); e.target.value = '' }}
        />
      </div>

      {file && (
        <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface-2 px-3.5 py-2.5">
          <FileText className="size-5 shrink-0 text-info" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{file.name}</p>
            <p className="text-xs text-muted-foreground">{formatBytes(file.size)}</p>
          </div>
          <button type="button" onClick={() => onFile(null, null)} disabled={disabled}
            className="text-muted-foreground hover:text-foreground" aria-label="Remove file">
            <X className="size-4" />
          </button>
        </div>
      )}
    </div>
  )
}
