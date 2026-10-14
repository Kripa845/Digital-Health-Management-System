/**
 * AssignDoctorButton
 * ------------------
 * Lets an admin assign a patient to a recommended doctor in one click. Shows
 * "Assigned" when that doctor already looks after the patient. Assigning also
 * gives the doctor access to the patient's record (POST /assignments/ records an
 * approved access request). Every button on a page shares one assignments query.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, UserPlus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/label'
import { SimpleSelect } from '@/components/ui/select'
import { assignmentService, patientService } from '@/lib/api'
import { apiError } from '@/features/admin/admin-utils'

const ASSIGNMENTS_KEY = ['admin', 'assignments', 'all'] as const

export function AssignDoctorButton({ doctorId, doctorName, patientId, patientName }: {
  doctorId: number
  doctorName: string
  patientId: number
  patientName: string
}) {
  const qc = useQueryClient()
  const assignments = useQuery({
    queryKey: ASSIGNMENTS_KEY,
    queryFn: () => assignmentService.list(),
  })
  const existing = (assignments.data ?? []).find((a) => a.doctor === doctorId && a.patient === patientId)
  const assign = useMutation({
    mutationFn: () => assignmentService.create(doctorId, patientId),
    onSuccess: () => {
      toast.success(`${patientName} is now assigned to Dr. ${doctorName}.`)
      qc.invalidateQueries({ queryKey: ['admin', 'assignments'] })
      qc.invalidateQueries({ queryKey: ['admin', 'access-requests'] })
    },
    onError: (err) => toast.error(apiError(err, 'Could not assign the patient.')),
  })

  if (assignments.isLoading) return <span className="text-xs text-muted-foreground">…</span>
  if (existing) {
    return existing.status === 'Active'
      ? <Badge variant="success"><CheckCircle2 />Assigned</Badge>
      : <Badge variant="neutral" title="This assignment is inactive. Reactivate it from the doctor's page.">Inactive assignment</Badge>
  }
  return (
    <Button type="button" size="sm" variant="secondary" loading={assign.isPending}
      onClick={() => assign.mutate()} aria-label={`Assign ${patientName} to Dr. ${doctorName}`}>
      {!assign.isPending && <UserPlus className="size-4" />}Assign
    </Button>
  )
}

/**
 * Assign a recommended doctor: straight away when the patient is known, otherwise
 * through a small dialog where the admin picks the patient first.
 */
export function AssignDoctorAction({ doctorId, doctorName, patient }: {
  doctorId: number
  doctorName: string
  patient: { id: number; name: string } | null
}) {
  if (patient) {
    return <AssignDoctorButton doctorId={doctorId} doctorName={doctorName} patientId={patient.id} patientName={patient.name} />
  }
  return <AssignWithPatientPicker doctorId={doctorId} doctorName={doctorName} />
}

function AssignWithPatientPicker({ doctorId, doctorName }: { doctorId: number; doctorName: string }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [patientId, setPatientId] = useState('')
  const patients = useQuery({
    queryKey: ['admin', 'patients', 'assign-picker'],
    queryFn: () => patientService.list({ status: 'Active' }),
    enabled: open,
  })
  const list = [...(patients.data ?? [])].sort((a, b) =>
    `${a.first_name} ${a.last_name}`.localeCompare(`${b.first_name} ${b.last_name}`))
  const chosen = list.find((p) => String(p.id) === patientId)
  const assign = useMutation({
    mutationFn: () => assignmentService.create(doctorId, Number(patientId)),
    onSuccess: () => {
      toast.success(`${chosen ? `${chosen.first_name} ${chosen.last_name}` : 'The patient'} is now assigned to Dr. ${doctorName}.`)
      qc.invalidateQueries({ queryKey: ['admin', 'assignments'] })
      qc.invalidateQueries({ queryKey: ['admin', 'access-requests'] })
      setOpen(false)
      setPatientId('')
    },
    onError: (err) => toast.error(apiError(err, 'Could not assign the patient.')),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button type="button" size="sm" variant="secondary" onClick={() => setOpen(true)}
        aria-label={`Assign a patient to Dr. ${doctorName}`}>
        <UserPlus className="size-4" />Assign
      </Button>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Assign to Dr. {doctorName}</DialogTitle>
          <DialogDescription>
            The doctor will also get access to this patient's record.
          </DialogDescription>
        </DialogHeader>
        <Field label="Patient" htmlFor={`assign-patient-${doctorId}`}>
          {patients.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading patients…</p>
          ) : (
            <SimpleSelect id={`assign-patient-${doctorId}`} value={patientId || undefined} onValueChange={setPatientId}
              placeholder="Choose a patient"
              options={list.map((p) => ({ value: String(p.id), label: `${p.first_name} ${p.last_name} · ${p.patient_id}` }))} />
          )}
        </Field>
        <DialogFooter>
          <DialogClose asChild><Button type="button" variant="secondary">Cancel</Button></DialogClose>
          <Button type="button" disabled={!patientId} loading={assign.isPending} onClick={() => assign.mutate()}>
            {!assign.isPending && <UserPlus className="size-4" />}Assign
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
