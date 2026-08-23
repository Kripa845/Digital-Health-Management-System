import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Eye, EyeOff, ShieldAlert, ArrowRight } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { AuthLayout } from './AuthLayout'
import { PasswordStrength } from '@/components/password-strength'
import { authService, session } from '@/lib/api'
import { useAuth, homePathFor } from '@/lib/auth'

export function ChangePasswordPage() {
  const navigate = useNavigate()
  const { refresh, role } = useAuth()
  const forced = session.mustChangePassword
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [show, setShow] = useState(false)
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (newPw.length < 8) return toast.error('New password must be at least 8 characters.')
    if (newPw !== confirm) return toast.error('Passwords do not match.')
    setLoading(true)
    try {
      await authService.changePassword(oldPw, newPw)
      toast.success('Your password has been updated.')
      await refresh()
      navigate(homePathFor(role), { replace: true })
    } catch (err: any) {
      toast.error(err.response?.data?.old_password?.[0] || err.response?.data?.detail || 'Could not update your password.')
    } finally { setLoading(false) }
  }

  return (
    <AuthLayout>
      {forced && (
        <div className="mb-6 flex items-start gap-3 rounded-[var(--radius-md)] border border-warning/30 bg-warning-soft p-3.5 text-sm text-warning">
          <ShieldAlert className="mt-0.5 size-5 shrink-0" />
          <p className="text-pretty">For your security, please set a new password before continuing.</p>
        </div>
      )}
      <h1 className="font-display text-2xl font-semibold tracking-tight">
        {forced ? 'Set a new password' : 'Change your password'}
      </h1>
      <p className="mt-1.5 text-sm text-muted-foreground">Choose something only you would know.</p>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field label="Current password">
          <div className="relative">
            <Input type={show ? 'text' : 'password'} value={oldPw} onChange={(e) => setOldPw(e.target.value)} className="pr-10" autoComplete="current-password" />
            <button type="button" onClick={() => setShow((v) => !v)} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
        </Field>
        <Field label="New password">
          <Input type={show ? 'text' : 'password'} value={newPw} onChange={(e) => setNewPw(e.target.value)} autoComplete="new-password" />
        </Field>
        <PasswordStrength value={newPw} />
        <Field label="Confirm new password" error={confirm && confirm !== newPw ? 'Passwords do not match' : undefined}>
          <Input type={show ? 'text' : 'password'} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
        </Field>
        <Button type="submit" loading={loading} size="lg" className="w-full">Update password <ArrowRight className="size-4" /></Button>
      </form>
    </AuthLayout>
  )
}
