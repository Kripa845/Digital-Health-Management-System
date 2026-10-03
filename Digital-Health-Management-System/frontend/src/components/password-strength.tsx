import { cn } from '@/lib/utils'

function scorePassword(pw: string): { score: number; label: string } {
  let score = 0
  if (pw.length >= 8) score++
  if (pw.length >= 12) score++
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++
  if (/\d/.test(pw)) score++
  if (/[^A-Za-z0-9]/.test(pw)) score++
  const clamped = Math.min(4, score)
  const labels = ['Too weak', 'Weak', 'Fair', 'Good', 'Strong']
  return { score: clamped, label: labels[clamped] }
}

export function PasswordStrength({ value }: { value: string }) {
  const { score, label } = scorePassword(value)
  const colors = ['bg-danger', 'bg-danger', 'bg-warning', 'bg-primary', 'bg-success']
  if (!value) return null
  return (
    <div className="space-y-1.5">
      <div className="flex gap-1.5">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className={cn('h-1.5 flex-1 rounded-full transition-colors', i < score ? colors[score] : 'bg-surface-3')} />
        ))}
      </div>
      <p className="text-xs text-muted-foreground">Password strength: <span className="font-medium text-foreground">{label}</span></p>
    </div>
  )
}
