import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Wordmark } from '@/components/brand'

export function NotFoundPage() {
  return (
    <div className="grid min-h-dvh place-items-center bg-background aurora px-4">
      <div className="text-center">
        <Link to="/" className="mb-8 inline-block"><Wordmark size="lg" /></Link>
        <p className="font-display text-7xl font-semibold text-primary">404</p>
        <h1 className="mt-2 font-display text-2xl font-semibold tracking-tight">This page took a different path</h1>
        <p className="mx-auto mt-2 max-w-sm text-muted-foreground text-pretty">
          We couldn't find what you were looking for. Let's get you back to safe ground.
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <Button asChild><Link to="/"><Compass className="size-4" /> Back home</Link></Button>
          <Button asChild variant="secondary"><Link to="/login">Sign in</Link></Button>
        </div>
      </div>
    </div>
  )
}
