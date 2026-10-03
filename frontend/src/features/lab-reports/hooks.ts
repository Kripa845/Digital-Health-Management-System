/**
 * Data hooks for lab reports and the health dashboard. All medical and
 * identity rules live on the server; these hooks only fetch and refresh.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { labReportService } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { ConfirmPayload } from '@/lib/types'

export const labKeys = {
  dashboard: (patientId?: number) => ['lab', 'dashboard', patientId ?? 'me'] as const,
  reports: (patientId?: number) => ['lab', 'reports', patientId ?? 'me'] as const,
  report: (id: number) => ['lab', 'report', id] as const,
  reviewQueue: () => ['lab', 'review-queue'] as const,
}

/** Refetch everything that shows lab data (including older 'lab-reports' keys). */
export function invalidateLab(qc: QueryClient) {
  return qc.invalidateQueries({
    predicate: (q) => q.queryKey[0] === 'lab' || q.queryKey.includes('lab-reports'),
  })
}

export function useDashboard(patientId?: number) {
  return useQuery({
    queryKey: labKeys.dashboard(patientId),
    queryFn: () => labReportService.dashboard(patientId),
  })
}

export function useLabReports(patientId?: number) {
  return useQuery({
    queryKey: labKeys.reports(patientId),
    queryFn: () => labReportService.list(patientId != null ? { patient: patientId } : undefined),
  })
}

export function useLabReport(id: number) {
  return useQuery({
    queryKey: labKeys.report(id),
    queryFn: () => labReportService.retrieve(id),
    enabled: Number.isFinite(id),
  })
}

export function useUploadReport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: { file: File; name?: string; patientId?: number; onProgress?: (pct: number) => void }) =>
      labReportService.upload(args.file, args),
    onSuccess: () => invalidateLab(qc),
  })
}

export function useConfirmReport() {
  const qc = useQueryClient()
  const { refresh } = useAuth()
  return useMutation({
    mutationFn: (args: { id: number; payload?: ConfirmPayload }) => labReportService.confirm(args.id, args.payload),
    onSuccess: async () => {
      // The dashboard cards and the profile both show the new values.
      await Promise.all([invalidateLab(qc), refresh()])
    },
  })
}

export function useSetReportDate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: { id: number; reportDate: string }) => labReportService.setReportDate(args.id, args.reportDate),
    onSuccess: () => invalidateLab(qc),
  })
}

export function useDiscardReport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => labReportService.discard(id),
    onSuccess: () => invalidateLab(qc),
  })
}

export function useReviewQueue() {
  return useQuery({ queryKey: labKeys.reviewQueue(), queryFn: labReportService.reviewQueue })
}

export function useResolveReport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: { id: number; decision: 'approve' | 'reject'; note?: string }) =>
      labReportService.resolve(args.id, args.decision, args.note),
    onSuccess: () => invalidateLab(qc),
  })
}
