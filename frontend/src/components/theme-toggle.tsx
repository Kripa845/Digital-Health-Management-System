import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/components/theme-provider'
import { cn } from '@/lib/utils'

export function ThemeToggle({ className }: { className?: string }) {
  const { toggle, resolved } = useTheme()
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      aria-label={`Switch to ${resolved === 'dark' ? 'light' : 'dark'} mode`}
      className={cn('text-muted-foreground', className)}
    >
      <Sun className={cn('size-5 transition-all', resolved === 'dark' ? 'scale-0 -rotate-90 absolute' : 'scale-100 rotate-0')} />
      <Moon className={cn('size-5 transition-all', resolved === 'dark' ? 'scale-100 rotate-0' : 'scale-0 rotate-90 absolute')} />
    </Button>
  )
}
