import { cn } from '@/lib/utils'

/** The Mero Care Card mark — a rounded cross + pulse, echoing a health card. */
export function Logo({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'grid place-items-center rounded-[var(--radius-md)] bg-gradient-to-br from-primary to-[color-mix(in_oklab,var(--primary)_70%,var(--accent))] text-primary-foreground shadow-[var(--shadow-glow)]',
        className,
      )}
    >
      <svg viewBox="0 0 24 24" fill="none" className="size-[62%]" aria-hidden="true">
        <path
          d="M3 12.5h3l1.6-3.4a.6.6 0 0 1 1.1.05L11 16.2a.6.6 0 0 0 1.13.06L14.2 10l1.1 2.2a.6.6 0 0 0 .54.33H21"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  )
}

export function Wordmark({ className, size = 'md' }: { className?: string; size?: 'sm' | 'md' | 'lg' }) {
  const logoSize = size === 'lg' ? 'size-10' : size === 'sm' ? 'size-7' : 'size-9'
  const textSize = size === 'lg' ? 'text-2xl' : size === 'sm' ? 'text-base' : 'text-lg'
  return (
    <span className={cn('flex items-center gap-2.5', className)}>
      <Logo className={logoSize} />
      <span className={cn('font-display font-semibold tracking-tight leading-none', textSize)}>
        Mero<span className="text-primary"> Care</span>
      </span>
    </span>
  )
}
