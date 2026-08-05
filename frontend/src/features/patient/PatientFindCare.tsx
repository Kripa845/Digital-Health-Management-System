import { HeartPulse, Clock, Stethoscope } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { PageHeader, DataState, EmptyState, SectionTitle } from '@/components/patterns'
import { Skeleton } from '@/components/ui/misc'
import { SymptomChecker } from '@/features/shared/SymptomChecker'
import { useAuth } from '@/lib/auth'
import { recommendationService } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'

export function PatientFindCare() {
  const { user, loading } = useAuth()
  const patientId = user?.patient_profile?.id

  const historyQ = useQuery({
    queryKey: ['patient', 'recommendations'],
    queryFn: () => recommendationService.list(),
  })
  const history = historyQ.data ?? []

  return (
    <div className="space-y-8">
      <PageHeader
        title="Find the right care"
        description="Describe how you're feeling and our transparent engine will point you to the right department and clinician."
        icon={HeartPulse}
      />

      {loading ? (
        <Skeleton className="h-80 rounded-[var(--radius-lg)]" />
      ) : (
        <div className="rounded-[var(--radius-xl)] border border-border bg-surface/60 p-4 sm:p-6">
          <SymptomChecker patientId={patientId} />
        </div>
      )}

      <section className="space-y-3">
        <SectionTitle>Your recent checks</SectionTitle>
        <DataState
          isLoading={historyQ.isLoading}
          isError={historyQ.isError}
          isEmpty={history.length === 0}
          onRetry={() => historyQ.refetch()}
          empty={<EmptyState icon={Clock} title="No checks yet" description="Your symptom checks and their recommendations will appear here." />}
        >
          <div className="space-y-3">
            {history.map((h, i) => (
              <Card key={h.id ?? i}>
                <CardContent className="space-y-2.5 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <Badge variant="primary"><Stethoscope />{h.recommended_department}</Badge>
                    <span className="text-xs text-muted-foreground">{formatDateTime(h.recommendation_date)}</span>
                  </div>
                  <p className="text-sm text-muted-foreground text-pretty italic">“{h.symptoms}”</p>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-subtle-foreground">
                    <span>Pain <strong className="text-foreground">{h.pain_level}/10</strong></span>
                    {h.confidence != null && <span>Confidence <strong className="text-foreground">{h.confidence}%</strong></span>}
                    {h.recommended_doctor_detail && (
                      <span>
                        Suggested{' '}
                        <strong className="text-foreground">
                          Dr. {h.recommended_doctor_detail.first_name} {h.recommended_doctor_detail.last_name}
                        </strong>
                      </span>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </DataState>
      </section>
    </div>
  )
}
