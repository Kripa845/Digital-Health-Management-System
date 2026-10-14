import type { LucideIcon } from 'lucide-react'
import {
  LayoutDashboard, Users, Stethoscope, CalendarDays,
  ShieldCheck, ScrollText, Settings, IdCard, FileText, ScanLine,
  UserCircle, FlaskConical, BrainCircuit, Activity, Siren,
} from 'lucide-react'
import type { Role } from '@/lib/types'

export interface NavItem {
  label: string
  to: string
  icon: LucideIcon
  end?: boolean
}

export interface NavSection {
  heading?: string
  items: NavItem[]
}

export const NAV: Record<Role, NavSection[]> = {
  ADMIN: [
    { items: [{ label: 'Overview', to: '/admin/dashboard', icon: LayoutDashboard }] },
    {
      heading: 'Manage',
      items: [
        { label: 'Patients', to: '/admin/patients', icon: Users },
        { label: 'Doctors', to: '/admin/doctors', icon: Stethoscope },
        { label: 'Appointments', to: '/admin/appointments', icon: CalendarDays },
        { label: 'Symptom Checker', to: '/admin/symptom-checker', icon: BrainCircuit },
      ],
    },
    {
      heading: 'Governance',
      items: [
        { label: 'Access Requests', to: '/admin/access-requests', icon: ShieldCheck },
        { label: 'Audit Log', to: '/admin/audit', icon: ScrollText },
        { label: 'Activity Analysis', to: '/admin/activity-analysis', icon: Activity },
        { label: 'Suspicious Alerts', to: '/admin/suspicious-alerts', icon: Siren },
        { label: 'Settings', to: '/admin/settings', icon: Settings },
      ],
    },
  ],
  DOCTOR: [
    { items: [{ label: 'Overview', to: '/doctor/dashboard', icon: LayoutDashboard }] },
    {
      heading: 'Care',
      items: [
        { label: 'My Patients', to: '/doctor/patients', icon: Users },
        { label: 'Scan a Card', to: '/doctor/scan', icon: ScanLine },
        { label: 'Appointments', to: '/doctor/appointments', icon: CalendarDays },
      ],
    },
    {
      heading: 'Account',
      items: [{ label: 'My Profile', to: '/doctor/profile', icon: UserCircle }],
    },
  ],
  PATIENT: [
    { items: [{ label: 'Overview', to: '/patient/dashboard', icon: LayoutDashboard }] },
    {
      heading: 'My Health',
      items: [
        { label: 'Health Card', to: '/patient/card', icon: IdCard },
        { label: 'Appointments', to: '/patient/appointments', icon: CalendarDays },
        { label: 'Lab Reports', to: '/patient/lab-reports', icon: FlaskConical },
        { label: 'Documents', to: '/patient/reports', icon: FileText },
        { label: 'Symptom Checker', to: '/patient/symptom-checker', icon: BrainCircuit },
      ],
    },
    {
      heading: 'Account',
      items: [{ label: 'My Profile', to: '/patient/profile', icon: UserCircle }],
    },
  ],
}

export const ROLE_LABEL: Record<Role, string> = {
  ADMIN: 'Administrator',
  DOCTOR: 'Clinician',
  PATIENT: 'Patient',
}
