import { Toaster as Sonner } from 'sonner'
import { useTheme } from '@/components/theme-provider'

export function Toaster() {
  const { resolved } = useTheme()
  return (
    <Sonner
      theme={resolved}
      position="top-right"
      richColors
      closeButton
      toastOptions={{
        style: {
          borderRadius: 'var(--radius-md)',
          fontFamily: 'var(--font-sans)',
        },
      }}
    />
  )
}
