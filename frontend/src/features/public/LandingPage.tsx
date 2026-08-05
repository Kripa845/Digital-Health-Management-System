import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Menu, X, ArrowRight, ShieldCheck, QrCode, CalendarDays,
  FileText, HeartPulse, Sparkles, ChevronDown, Lock, Zap, Users,
  Activity,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Wordmark, Logo } from '@/components/brand'
import { ThemeToggle } from '@/components/theme-toggle'
import { SymptomChecker } from '@/features/shared/SymptomChecker'
import { cn } from '@/lib/utils'

const NAV_LINKS = [
  { label: 'Features', href: '#features' },
  { label: 'How it works', href: '#how' },
  { label: 'Symptom checker', href: '#checker' },
  { label: 'FAQ', href: '#faq' },
]

function PublicNav() {
  const [open, setOpen] = useState(false)
  return (
    <header className="sticky top-0 z-50 border-b border-border/70 glass">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link to="/"><Wordmark /></Link>
        <nav className="hidden items-center gap-1 md:flex">
          {NAV_LINKS.map((l) => (
            <a key={l.href} href={l.href} className="rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground">
              {l.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-1.5">
          <ThemeToggle />
          <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex"><Link to="/login">Sign in</Link></Button>
          <Button asChild size="sm" className="hidden sm:inline-flex"><a href="#checker">Try it free</a></Button>
          <button className="rounded-md p-2 text-muted-foreground md:hidden" onClick={() => setOpen((v) => !v)} aria-label="Menu">
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
      </div>
      {open && (
        <div className="border-t border-border px-4 pb-4 md:hidden">
          <nav className="flex flex-col gap-1 pt-2">
            {NAV_LINKS.map((l) => (
              <a key={l.href} href={l.href} onClick={() => setOpen(false)} className="rounded-md px-3 py-2.5 text-sm font-medium text-muted-foreground hover:bg-surface-2">{l.label}</a>
            ))}
            <Button asChild className="mt-2"><Link to="/login">Sign in</Link></Button>
          </nav>
        </div>
      )}
    </header>
  )
}

function HealthCardVisual() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24, rotateX: 8 }}
      animate={{ opacity: 1, y: 0, rotateX: 0 }}
      transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
      className="relative mx-auto w-full max-w-sm"
      style={{ perspective: 1000 }}
    >
      {/* Floating accents */}
      <motion.div
        aria-hidden
        animate={{ y: [0, -10, 0] }}
        transition={{ duration: 5, repeat: Infinity, ease: 'easeInOut' }}
        className="absolute -right-5 -top-5 z-10 rounded-[var(--radius-lg)] border border-border bg-surface p-3 shadow-[var(--shadow-md)]"
      >
        <div className="flex items-center gap-2">
          <span className="grid size-8 place-items-center rounded-full bg-success-soft text-success"><ShieldCheck className="size-4" /></span>
          <div>
            <p className="text-[11px] font-semibold leading-tight">Verified</p>
            <p className="text-[10px] leading-tight text-subtle-foreground">Secure UUID</p>
          </div>
        </div>
      </motion.div>
      <motion.div
        aria-hidden
        animate={{ y: [0, 12, 0] }}
        transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut', delay: 0.5 }}
        className="absolute -bottom-6 -left-6 z-10 rounded-[var(--radius-lg)] border border-border bg-surface p-3 shadow-[var(--shadow-md)]"
      >
        <div className="flex items-center gap-2">
          <span className="grid size-8 place-items-center rounded-full bg-primary-soft text-primary-soft-foreground"><HeartPulse className="size-4" /></span>
          <div>
            <p className="text-[11px] font-semibold leading-tight">A+ · O.K.</p>
            <p className="text-[10px] leading-tight text-subtle-foreground">Blood group on file</p>
          </div>
        </div>
      </motion.div>

      {/* The card */}
      <div className="relative overflow-hidden rounded-[var(--radius-2xl)] border border-border bg-gradient-to-br from-surface to-surface-2 p-6 shadow-[var(--shadow-lg)]">
        <div className="absolute -right-16 -top-16 size-48 rounded-full bg-primary/10 blur-2xl" />
        <div className="relative flex items-start justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-primary">Digital Health Card</p>
            <p className="font-display text-lg font-semibold">Aayush Sharma</p>
          </div>
          <Logo className="size-9" />
        </div>
        <div className="relative mt-6 flex items-center gap-5">
          <div className="grid size-24 place-items-center rounded-[var(--radius-md)] border border-border bg-surface p-2">
            <QrCode className="size-full text-foreground" strokeWidth={1} />
          </div>
          <div className="flex-1 space-y-2.5">
            <div>
              <p className="text-[10px] uppercase tracking-wide text-subtle-foreground">Patient ID</p>
              <p className="font-mono text-sm font-medium">PAT-1A2B3C4D</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-subtle-foreground">Emergency</p>
              <p className="font-mono text-sm font-medium">+977 98•• ••7788</p>
            </div>
            <Badge variant="success" className="mt-1">Active</Badge>
          </div>
        </div>
        <div className="relative mt-5 flex items-center justify-between border-t border-border pt-4 text-xs text-muted-foreground">
          <span>Scan for emergency identity</span>
          <span className="font-mono">mero.care</span>
        </div>
      </div>
    </motion.div>
  )
}

const FEATURES = [
  { icon: QrCode, title: 'Scannable health card', body: 'Every patient carries a QR card that reveals identity essentials in an emergency — never their private records.' },
  { icon: HeartPulse, title: 'Guided doctor matching', body: 'Describe symptoms in plain words; a transparent scoring engine routes you to the right department and clinician.' },
  { icon: ShieldCheck, title: 'Role-based privacy', body: 'Patients, doctors, and admins each see exactly what they should — enforced on every request, not just the screen.' },
  { icon: CalendarDays, title: 'Appointments that flow', body: 'Request, accept, complete — a clear lifecycle with notifications, so nothing slips between visits.' },
  { icon: FileText, title: 'Records, organised', body: 'Prescriptions and reports kept tidy, versioned, and downloadable — protected behind granular permissions.' },
  { icon: Lock, title: 'Secure by default', body: 'JWT sessions, email two-factor sign-in, audit trails, and OTP recovery keep every account safe.' },
]

const STEPS = [
  { n: '01', title: 'Get your card', body: 'Your clinic registers you and issues a secure digital health card with a unique QR identity.' },
  { n: '02', title: 'Share when it matters', body: 'Present your card at reception or in an emergency — care teams see only what they need.' },
  { n: '03', title: 'Find the right care', body: 'Use the symptom checker to reach the right specialist, then book and track appointments.' },
]

const FAQS = [
  { q: 'What is Mero Care Card?', a: 'A secure digital health platform. Each patient gets a scannable QR card for instant, privacy-respecting access to essential medical identity, plus tools for appointments, records, and doctor matching.' },
  { q: 'Who can see my medical records?', a: 'Only you and the clinicians assigned to your care. A public QR scan reveals identity essentials only — never your allergies, medications, or reports. Access is enforced on the server, per request.' },
  { q: 'How does doctor matching work?', a: 'You describe your symptoms, pain level, and age. A transparent rule-based engine scores departments and available doctors, and explains why it recommends each match.' },
  { q: 'Can I edit my own medical record?', a: 'To keep records clinically valid, only administrators edit core profiles. You can upload your own additional reports and manage your appointments.' },
  { q: 'Is signing in secure?', a: 'Yes. Sign-in uses email two-factor verification, sessions are short-lived and refreshed securely, and password recovery uses single-use OTP codes.' },
]

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-[var(--radius-md)] border border-border bg-surface">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left">
        <span className="font-medium">{q}</span>
        <ChevronDown className={cn('size-5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>
      <div className={cn('grid transition-all duration-300', open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0')}>
        <div className="overflow-hidden">
          <p className="px-5 pb-4 text-sm text-muted-foreground text-pretty leading-relaxed">{a}</p>
        </div>
      </div>
    </div>
  )
}

export function LandingPage() {
  return (
    <div className="min-h-dvh bg-background">
      <PublicNav />

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 aurora opacity-70" aria-hidden />
        <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:py-24">
          <motion.div
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="space-y-7"
          >
            <Badge variant="primary" className="px-3 py-1"><Sparkles className="size-3.5" />Digital health, built for Nepal</Badge>
            <h1 className="font-display text-4xl font-semibold leading-[1.05] tracking-tight text-balance sm:text-5xl lg:text-6xl">
              Your whole health story, in{' '}
              <span className="text-primary">one gentle card.</span>
            </h1>
            <p className="max-w-xl text-lg text-muted-foreground text-pretty leading-relaxed">
              Mero Care Card gives every patient a secure QR health card, guides them to the right doctor,
              and keeps records private — so in the moments that matter, the right care is never out of reach.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Button asChild size="lg"><a href="#checker">Try the symptom checker <ArrowRight className="size-4" /></a></Button>
              <Button asChild size="lg" variant="secondary"><a href="#features">See how it works</a></Button>
            </div>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 pt-2 text-sm text-muted-foreground">
              {[[ShieldCheck, 'Private by design'], [Zap, 'Emergency-ready'], [Users, 'For every role']].map(([Icon, t]: any) => (
                <span key={t} className="flex items-center gap-1.5"><Icon className="size-4 text-primary" />{t}</span>
              ))}
            </div>
          </motion.div>
          <HealthCardVisual />
        </div>
      </section>

      {/* Features */}
      <section id="features" className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-wide text-primary">Everything in one place</p>
          <h2 className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl text-balance">A calmer way to run care</h2>
          <p className="mt-3 text-muted-foreground text-pretty">Thoughtful tools for patients and clinics — designed to feel human, and built to keep data safe.</p>
        </div>
        <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.45, delay: (i % 3) * 0.06 }}
              className="group rounded-[var(--radius-lg)] border border-border bg-surface p-6 shadow-[var(--shadow-xs)] transition-all hover:shadow-[var(--shadow-md)] hover:-translate-y-0.5"
            >
              <span className="grid size-11 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground transition-colors">
                <f.icon className="size-5.5" />
              </span>
              <h3 className="mt-4 font-semibold">{f.title}</h3>
              <p className="mt-1.5 text-sm text-muted-foreground text-pretty leading-relaxed">{f.body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="border-y border-border bg-surface/60">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-wide text-primary">Three simple steps</p>
            <h2 className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">From sign-up to the right specialist</h2>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            {STEPS.map((s) => (
              <div key={s.n} className="relative rounded-[var(--radius-lg)] border border-border bg-surface p-6">
                <span className="font-display text-4xl font-semibold text-primary/25">{s.n}</span>
                <h3 className="mt-2 text-lg font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm text-muted-foreground text-pretty leading-relaxed">{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Symptom checker */}
      <section id="checker" className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <div className="grid gap-8 lg:grid-cols-[0.9fr_1.4fr] lg:items-start">
          <div className="space-y-4 lg:sticky lg:top-24">
            <Badge variant="info"><Activity className="size-3.5" />Live demo</Badge>
            <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl text-balance">Not sure who to see?</h2>
            <p className="text-muted-foreground text-pretty leading-relaxed">
              Describe how you're feeling in your own words. Our engine weighs your symptoms, pain, age and history,
              then explains which department and clinician fit best — transparently, with a confidence score.
            </p>
            <p className="text-sm text-subtle-foreground">No account needed to try it.</p>
          </div>
          <div className="rounded-[var(--radius-xl)] border border-border bg-surface/60 p-4 sm:p-6">
            <SymptomChecker />
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="border-t border-border bg-surface/60">
        <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:py-24">
          <h2 className="text-center font-display text-3xl font-semibold tracking-tight sm:text-4xl">Questions, answered</h2>
          <div className="mt-10 space-y-3">
            {FAQS.map((f) => <FaqItem key={f.q} {...f} />)}
          </div>
        </div>
      </section>

      {/* Closing CTA */}
      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <div className="relative overflow-hidden rounded-[var(--radius-2xl)] border border-border bg-surface p-8 text-center sm:p-14">
          <div className="absolute inset-0 aurora opacity-70" aria-hidden />
          <div className="relative">
            <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl text-balance">
              Care that's ready when you are
            </h2>
            <p className="mx-auto mt-3 max-w-xl text-muted-foreground text-pretty">
              Sign in to your Mero Care Card, or try the symptom checker to find the right doctor in minutes.
            </p>
            <div className="mt-7 flex flex-wrap justify-center gap-3">
              <Button asChild size="lg"><Link to="/login">Sign in</Link></Button>
              <Button asChild size="lg" variant="secondary"><a href="#checker">Try the symptom checker</a></Button>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-4 py-10 sm:flex-row sm:px-6">
          <Wordmark />
          <p className="text-sm text-muted-foreground">© {new Date().getFullYear()} Mero Care Card. Caring, secure, and yours.</p>
          <div className="flex gap-4 text-sm">
            <Link to="/login" className="text-muted-foreground hover:text-foreground">Sign in</Link>
            <a href="#faq" className="text-muted-foreground hover:text-foreground">FAQ</a>
          </div>
        </div>
      </footer>
    </div>
  )
}
