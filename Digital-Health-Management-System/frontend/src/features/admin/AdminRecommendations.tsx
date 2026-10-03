import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Sparkles, Stethoscope } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { SimpleSelect } from '@/components/ui/select'
import { Field } from '@/components/ui/label'
import { PageHeader, DataState, EmptyState, ListSkeleton, SectionTitle } from '@/components/patterns'
import { recommendationService, patientService } from '@/lib/api'
import type { Recommendation, Patient } from '@/lib/types'
import { formatDateTime } from '@/lib/utils'
import { SymptomChecker } from '@/features/shared/SymptomChecker'
import {
  ConfidenceBadge,
} from './admin-common'
import {
  tableHeadClass,
} from './admin-utils'

function doctorName(r: Recommendation) {
  const d = r.recommended_doctor_detail
  if (d) return `Dr. ${d.first_name ?? ''} ${d.last_name ?? ''}`.trim()
  return '—'
}

function excerpt(text: string, max = 80) {
  if (text.length <= max) return text
  return `${text.slice(0, max).trimEnd()}…`
}

export function AdminRecommendations() {
  const [patientId, setPatientId] = useState('none')

  const historyQ = useQuery({
    queryKey: ['admin', 'recommendations'],
    queryFn: () => recommendationService.list(),
  })
  const patientsQ = useQuery({
    queryKey: ['admin', 'patients', 'active-picker'],
    queryFn: () => patientService.list({ status: 'Active' }),
  })
  const history = historyQ.data ?? []
  const patients = patientsQ.data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Recommendations"
        description="Review past symptom checks and run a new department recommendation for any patient."
        icon={Sparkles}
      />

      {/* Run a check */}
      <Card className="p-5 sm:p-6">
        <SectionTitle className="mb-4">Run a check for a patient</SectionTitle>
        <div className="max-w-md">
          <Field label="Patient" hint="Optional — links the recommendation to a patient record">
            <SimpleSelect
              value={patientId}
              onValueChange={setPatientId}
              placeholder="Choose a patient (or run unlinked)"
              options={[
                { value: 'none', label: 'No patient (unlinked)' },
                ...patients.map((p: Patient) => ({ value: String(p.id), label: `${p.patient_id} · ${p.first_name} ${p.last_name}` })),
              ]}
            />
          </Field>
        </div>
        <div className="mt-5">
          <SymptomChecker patientId={patientId !== 'none' ? Number(patientId) : undefined} />
        </div>
      </Card>

      {/* History */}
      <section className="space-y-3">
        <SectionTitle>Recommendation history</SectionTitle>
        <DataState
          isLoading={historyQ.isLoading}
          isError={historyQ.isError}
          isEmpty={history.length === 0}
          onRetry={() => historyQ.refetch()}
          skeleton={<ListSkeleton rows={6} />}
          empty={<EmptyState icon={Stethoscope} title="No recommendations yet" description="Symptom checks will appear here once run." />}
        >
          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border bg-surface-2">
                  <tr>
                    <th className={tableHeadClass()}>Date</th>
                    <th className={tableHeadClass()}>Patient</th>
                    <th className={tableHeadClass()}>Symptoms</th>
                    <th className={tableHeadClass()}>Department</th>
                    <th className={tableHeadClass()}>Confidence</th>
                    <th className={tableHeadClass()}>Recommended doctor</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {history.map((r) => (
                    <tr key={r.id ?? `${r.recommendation_date}-${r.symptoms}`} className="transition-colors hover:bg-surface-2/60">
                      <td className="whitespace-nowrap px-4 py-3 tabular-nums text-muted-foreground">{formatDateTime(r.recommendation_date)}</td>
                      <td className="px-4 py-3">{r.patient_name || '—'}</td>
                      <td className="max-w-xs px-4 py-3 text-muted-foreground">{excerpt(r.symptoms)}</td>
                      <td className="px-4 py-3 font-medium">{r.recommended_department}</td>
                      <td className="px-4 py-3"><ConfidenceBadge value={r.confidence} /></td>
                      <td className="px-4 py-3">{doctorName(r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </DataState>
      </section>
    </div>
  )
}
