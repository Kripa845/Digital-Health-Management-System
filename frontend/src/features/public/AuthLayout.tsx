import { Link } from 'react-router-dom'
import { ShieldCheck, QrCode, HeartPulse } from 'lucide-react'
import { Wordmark } from '@/components/brand'
import { ThemeToggle } from '@/components/theme-toggle'

export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      {/* Brand panel */}
      <div className="relative hidden overflow-hidden bg-primary text-primary-foreground lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="absolute inset-0 opacity-90" style={{ background: 'radial-gradient(70% 60% at 20% 10%, color-mix(in oklab, white 22%, transparent), transparent 60%), radial-gradient(60% 60% at 100% 100%, color-mix(in oklab, black 24%, transparent), transparent 55%)' }} aria-hidden />
        <div className="relative">
          <Link to="/"><Wordmark className="[&_.text-primary]:text-white/80 text-white" /></Link>
        </div>
        <div className="relative space-y-8">
          <blockquote className="space-y-4">
            <p className="font-display text-3xl font-semibold leading-tight text-balance">
              “In the moments that matter most, the right information should never be out of reach.”
            </p>
            <footer className="text-sm text-primary-foreground/70">The Mero Care Card promise</footer>
          </blockquote>
          <div className="flex flex-wrap gap-x-6 gap-y-3 text-sm text-primary-foreground/85">
            {[[ShieldCheck, 'Private by design'], [QrCode, 'Emergency-ready cards'], [HeartPulse, 'Guided doctor matching']].map(([Icon, t]: any) => (
              <span key={t} className="flex items-center gap-2"><Icon className="size-4" />{t}</span>
            ))}
          </div>
        </div>
        <p className="relative text-xs text-primary-foreground/60">© {new Date().getFullYear()} Mero Care Card</p>
      </div>

      {/* Form panel */}
      <div className="relative flex flex-col">
        <div className="flex items-center justify-between p-5 lg:justify-end">
          <Link to="/" className="lg:hidden"><Wordmark size="sm" /></Link>
          <ThemeToggle />
        </div>
        <div className="flex flex-1 items-center justify-center px-5 pb-16">
          <div className="w-full max-w-sm">{children}</div>
        </div>
      </div>
    </div>
  )
}
