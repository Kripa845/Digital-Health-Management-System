import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Eye, EyeOff, ArrowRight } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { AuthLayout } from './AuthLayout'
import { authService } from '@/lib/api'
import { useAuth, homePathFor } from '@/lib/auth'

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { refresh } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) return toast.error('Enter your username and password.')
    setLoading(true)
    try {
      const res = await authService.login(username.trim(), password)
      if (res.access) {
        toast.success('Welcome back.')
        await refresh()
        const dest = homePathFor((res.role as any) ?? undefined)
        navigate((location.state as any)?.from?.pathname || dest, { replace: true })
      }
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Those credentials did not match. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout>
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <div className="space-y-2">
          <h1 className="font-display text-3xl font-semibold tracking-tight">Welcome back</h1>
          <p className="text-sm text-muted-foreground">Sign in to your Mero Care Card account.</p>
        </div>
        <form onSubmit={submit} className="mt-8 space-y-4">
          <Field label="Username" htmlFor="username">
            <Input id="username" autoFocus autoComplete="username" value={username}
              onChange={(e) => setUsername(e.target.value)} placeholder="e.g. hari.tamang" />
          </Field>
          <Field label="Password" htmlFor="password">
            <div className="relative">
              <Input id="password" type={showPw ? 'text' : 'password'} autoComplete="current-password" value={password}
                onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" className="pr-10" />
              <button type="button" onClick={() => setShowPw((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label={showPw ? 'Hide password' : 'Show password'}>
                {showPw ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </Field>
          <Button type="submit" loading={loading} size="lg" className="w-full">Sign in <ArrowRight className="size-4" /></Button>
        </form>
        <p className="mt-6 text-center text-sm text-muted-foreground">
          New to Mero Care Card? <Link to="/" className="font-medium text-primary hover:underline">Learn more</Link>
        </p>
      </motion.div>
    </AuthLayout>
  )
}
