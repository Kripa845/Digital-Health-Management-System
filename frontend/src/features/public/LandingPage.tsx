import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowRight, ShieldCheck, QrCode, CalendarDays, Activity,
  BadgeCheck, Phone, Mail, MapPin, Siren,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Wordmark, Logo } from '@/components/brand'
import { ThemeToggle } from '@/components/theme-toggle'
import { cn } from '@/lib/utils'
import heroImg from '@/assets/landing/hero-illustration.webp'

const EMERGENCY_NUMBER = '102'

const fadeUp = {
  initial: { opacity: 0, y: 18 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, margin: '-60px' },
  transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] as const },
}

function Eyebrow({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-full bg-primary-soft px-3 py-1 text-xs font-medium text-primary-soft-foreground', className)}>
      {children}
    </span>
  )
}

function PublicNav() {
  return (
    <header className="sticky top-0 z-50 border-b border-border/60 glass">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link to="/"><Wordmark /></Link>
        <div className="flex items-center gap-1.5">
          <ThemeToggle />
          <Button asChild variant="ghost" size="sm" className="hidden rounded-full sm:inline-flex"><Link to="/login">Sign in</Link></Button>
          <Button asChild size="sm" className="rounded-full"><Link to="/login">Get started</Link></Button>
        </div>
      </div>
    </header>
  )
}

function HeroVisual() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1], delay: 0.1 }}
      className="relative mx-auto w-full max-w-md lg:max-w-none"
    >
      <div className="relative overflow-hidden rounded-[2rem] bg-gradient-to-br from-primary-soft via-surface-2 to-primary-soft px-6 pb-0 pt-14 shadow-[var(--shadow-lg)] sm:px-10">
        <img
          src={heroImg}
          alt="Doctor consulting a patient through a phone"
          className="mx-auto aspect-[849/927] w-full max-w-md object-contain"
          loading="eager"
        />
      </div>

      {/* Floating: next appointment */}
      <motion.div
        animate={{ y: [0, -8, 0] }}
        transition={{ duration: 5, repeat: Infinity, ease: 'easeInOut' }}
        className="absolute -left-3 top-8 flex items-center gap-3 rounded-2xl border border-border bg-surface px-4 py-3 shadow-[var(--shadow-md)] sm:-left-8"
      >
        <span className="grid size-9 place-items-center rounded-xl bg-primary-soft text-primary"><CalendarDays className="size-4" /></span>
        <div>
          <p className="text-[11px] leading-tight text-subtle-foreground">Next appointment</p>
          <p className="text-sm font-semibold leading-tight">Today, 2:30 PM</p>
        </div>
      </motion.div>

      {/* Floating: status pill */}
      <div className="absolute right-4 top-4 flex items-center gap-2 rounded-full bg-foreground px-3 py-1.5 text-xs font-medium text-background shadow-[var(--shadow-md)]">
        <span className="size-1.5 rounded-full bg-primary" />
        Emergency QR ready
      </div>

      {/* Floating: CTA pill */}
      <Link
        to="/login"
        className="absolute -right-2 top-[42%] flex items-center gap-2 rounded-full bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition-transform hover:scale-[1.03] sm:-right-6"
      >
        <CalendarDays className="size-4" />
        Book now
      </Link>

      {/* Floating: mini health card */}
      <motion.div
        animate={{ y: [0, 8, 0] }}
        transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut', delay: 0.5 }}
        className="absolute -bottom-6 right-4 w-56 rounded-2xl border border-border bg-surface p-4 shadow-[var(--shadow-lg)] sm:-right-4"
      >
        <div className="flex items-center justify-between">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">Health card</p>
          <Logo className="size-6" />
        </div>
        <div className="mt-3 flex items-center gap-3">
          <span className="grid size-12 place-items-center rounded-lg border border-border bg-background">
            <QrCode className="size-8" strokeWidth={1.3} />
          </span>
          <div>
            <p className="font-mono text-xs font-medium">PAT-1A2B3C4D</p>
            <p className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-success">
              <span className="size-1.5 rounded-full bg-success" />Active
            </p>
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}

export function LandingPage() {
  return (
    <div className="min-h-dvh overflow-x-clip bg-background">
      <PublicNav />

      {/* Hero */}
      <section className="relative">
        <div className="absolute inset-x-0 top-0 h-full bg-gradient-to-b from-primary-soft/40 to-transparent" aria-hidden />
        <div className="relative mx-auto grid max-w-6xl items-center gap-14 px-4 pb-20 pt-12 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pb-28 lg:pt-16">
          <motion.div
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="max-w-xl"
          >
            <Eyebrow>Digital health card for Nepal</Eyebrow>
            <h1 className="mt-6 text-5xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
              Your Health,
              <span className="block text-primary">Always Within Reach</span>
            </h1>
            <p className="mt-6 text-lg leading-relaxed text-muted-foreground text-pretty">
              Your health information, appointments and reports in one secure place.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg" className="rounded-full px-6">
                <Link to="/login">Get started <ArrowRight className="size-4" /></Link>
              </Button>
            </div>
            <div className="mt-8 flex flex-wrap gap-2.5">
              {[
                [Activity, '24/7 emergency QR'],
                [BadgeCheck, 'Verified doctors'],
                [ShieldCheck, 'Private by design'],
              ].map(([Icon, label]) => {
                const I = Icon as typeof Activity
                return (
                  <span key={label as string} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-muted-foreground">
                    <I className="size-3.5 text-primary" />{label as string}
                  </span>
                )
              })}
            </div>
          </motion.div>
          <div className="px-4 sm:px-8 lg:px-6">
            <HeroVisual />
          </div>
        </div>
      </section>

      {/* Closing CTA */}
      <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6 lg:pb-24">
        <motion.div
          {...fadeUp}
          className="relative overflow-hidden rounded-[2rem] bg-gradient-to-br from-[#1f8f5f] to-[#0f6b4a] p-8 text-white sm:p-14"
        >
          <svg aria-hidden viewBox="0 0 24 24" className="absolute -right-6 -top-6 size-48 text-white/10" fill="currentColor">
            <path d="M9 2h6v7h7v6h-7v7H9v-7H2V9h7z" />
          </svg>
          <div className="relative flex flex-col justify-between gap-10 md:flex-row md:items-center">
            <div className="max-w-lg">
              <span className="inline-flex items-center gap-2 rounded-full bg-white/15 px-3 py-1 text-xs font-medium">
                <span className="size-1.5 rounded-full bg-white" />Available 24/7
              </span>
              <h2 className="mt-5 text-3xl font-semibold leading-tight tracking-tight sm:text-5xl">Need medical assistance?</h2>
              <p className="mt-4 text-white/80 text-pretty">
                Sign in to book an appointment and view your reports.
              </p>
            </div>
            <div className="flex flex-col gap-5">
              <Link
                to="/login"
                className="inline-flex items-center justify-center gap-2 rounded-full bg-white px-6 py-3 text-sm font-semibold text-[#0f6b4a] shadow-lg transition-transform hover:scale-[1.03]"
              >
                Book appointment <ArrowRight className="size-4" />
              </Link>
              <a href={`tel:${EMERGENCY_NUMBER}`} className="flex items-center gap-3">
                <span className="grid size-10 place-items-center rounded-full bg-white/15"><Siren className="size-4" /></span>
                <span>
                  <span className="block text-xs text-white/70">Ambulance (Nepal)</span>
                  <span className="block font-semibold">{EMERGENCY_NUMBER}</span>
                </span>
              </a>
            </div>
          </div>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="bg-[#0f2a22] text-white/70">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1.5fr_1fr]">
          <div>
            <div className="flex items-center gap-2.5">
              <Logo className="size-9" />
              <span className="text-lg font-semibold text-white">Mero Care Card</span>
            </div>
            <p className="mt-4 max-w-xs text-sm leading-relaxed">
              A secure digital health card for patients, doctors and clinics in Nepal.
            </p>
            <ul className="mt-5 space-y-2.5 text-sm">
              <li className="flex items-center gap-2.5"><MapPin className="size-4 text-[#4fd1a5]" />Kathmandu, Nepal</li>
              <li className="flex items-center gap-2.5"><Mail className="size-4 text-[#4fd1a5]" />Support through your clinic</li>
            </ul>
          </div>
          <div>
            <p className="text-sm font-semibold text-white">Get started</p>
            <p className="mt-4 text-sm leading-relaxed">Registered by your clinic? Sign in to get started.</p>
            <Link
              to="/login"
              className="mt-4 inline-flex items-center gap-2 rounded-full bg-[#1f8f5f] px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#23a06b]"
            >
              Sign in <ArrowRight className="size-4" />
            </Link>
            <a href={`tel:${EMERGENCY_NUMBER}`} className="mt-5 flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 p-3">
              <span className="grid size-9 place-items-center rounded-full bg-white/10 text-[#4fd1a5]"><Phone className="size-4" /></span>
              <span>
                <span className="block text-xs">Emergency ambulance</span>
                <span className="block font-semibold text-white">{EMERGENCY_NUMBER}</span>
              </span>
            </a>
          </div>
        </div>
        <div className="border-t border-white/10">
          <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 px-4 py-6 text-xs sm:flex-row sm:px-6">
            <p>© {new Date().getFullYear()} Mero Care Card. All rights reserved.</p>
            <p>In an emergency, call {EMERGENCY_NUMBER} for an ambulance.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
