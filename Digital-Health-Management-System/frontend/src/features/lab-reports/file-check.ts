// A quick check for a better message before uploading; the server checks the
// file's real content type and size again.
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
const ACCEPTED = ['pdf', 'png', 'jpg', 'jpeg']

export function checkFile(f: File): string | null {
  const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
  if (!ACCEPTED.includes(ext)) return 'Choose a PDF, PNG or JPG file.'
  if (f.size > MAX_UPLOAD_BYTES) return 'The file is larger than 10 MB.'
  if (f.size === 0) return 'The file is empty.'
  return null
}
