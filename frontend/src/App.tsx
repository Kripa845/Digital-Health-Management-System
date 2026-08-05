import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { PrivateRoute, RoleRoute, PublicOnlyRoute } from '@/components/route-guards'
import { AppShell } from '@/components/app-shell'
import { Logo } from '@/components/brand'

// Public (landing kept eager-ish but still split from portals)
const LandingPage = lazy(() => import('@/features/public/LandingPage').then((m) => ({ default: m.LandingPage })))
const LoginPage = lazy(() => import('@/features/public/LoginPage').then((m) => ({ default: m.LoginPage })))
const ChangePasswordPage = lazy(() => import('@/features/public/ChangePasswordPage').then((m) => ({ default: m.ChangePasswordPage })))
const PublicProfilePage = lazy(() => import('@/features/public/PublicProfilePage').then((m) => ({ default: m.PublicProfilePage })))
const NotFoundPage = lazy(() => import('@/features/public/NotFoundPage').then((m) => ({ default: m.NotFoundPage })))

const PatientDashboard = lazy(() => import('@/features/patient/PatientDashboard').then((m) => ({ default: m.PatientDashboard })))
const PatientCard = lazy(() => import('@/features/patient/PatientCard').then((m) => ({ default: m.PatientCard })))
const PatientAppointments = lazy(() => import('@/features/patient/PatientAppointments').then((m) => ({ default: m.PatientAppointments })))
const PatientReports = lazy(() => import('@/features/patient/PatientReports').then((m) => ({ default: m.PatientReports })))
const PatientFindCare = lazy(() => import('@/features/patient/PatientFindCare').then((m) => ({ default: m.PatientFindCare })))
const PatientProfile = lazy(() => import('@/features/patient/PatientProfile').then((m) => ({ default: m.PatientProfile })))

const DoctorDashboard = lazy(() => import('@/features/doctor/DoctorDashboard').then((m) => ({ default: m.DoctorDashboard })))
const DoctorPatients = lazy(() => import('@/features/doctor/DoctorPatients').then((m) => ({ default: m.DoctorPatients })))
const DoctorScan = lazy(() => import('@/features/doctor/DoctorScan').then((m) => ({ default: m.DoctorScan })))
const DoctorAppointments = lazy(() => import('@/features/doctor/DoctorAppointments').then((m) => ({ default: m.DoctorAppointments })))
const DoctorProfile = lazy(() => import('@/features/doctor/DoctorProfile').then((m) => ({ default: m.DoctorProfile })))

const AdminDashboard = lazy(() => import('@/features/admin/AdminDashboard').then((m) => ({ default: m.AdminDashboard })))
const AdminPatients = lazy(() => import('@/features/admin/AdminPatients').then((m) => ({ default: m.AdminPatients })))
const AdminDoctors = lazy(() => import('@/features/admin/AdminDoctors').then((m) => ({ default: m.AdminDoctors })))
const AdminAppointments = lazy(() => import('@/features/admin/AdminAppointments').then((m) => ({ default: m.AdminAppointments })))
const AdminRecommendations = lazy(() => import('@/features/admin/AdminRecommendations').then((m) => ({ default: m.AdminRecommendations })))
const AdminAccessRequests = lazy(() => import('@/features/admin/AdminAccessRequests').then((m) => ({ default: m.AdminAccessRequests })))
const AdminAudit = lazy(() => import('@/features/admin/AdminAudit').then((m) => ({ default: m.AdminAudit })))
const AdminSettings = lazy(() => import('@/features/admin/AdminSettings').then((m) => ({ default: m.AdminSettings })))

function RouteFallback() {
  return (
    <div className="grid min-h-[60vh] place-items-center">
      <Logo className="size-11 animate-pulse" />
    </div>
  )
}

const shell = (el: React.ReactNode) => (
  <AppShell>
    <Suspense fallback={<RouteFallback />}>{el}</Suspense>
  </AppShell>
)

export default function App() {
  return (
    <Suspense fallback={<div className="grid min-h-dvh place-items-center bg-background"><Logo className="size-12 animate-pulse" /></div>}>
      <Routes>
        {/* Public */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/public-profile/:uuid" element={<PublicProfilePage />} />
        <Route element={<PublicOnlyRoute />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>

        {/* Authenticated */}
        <Route element={<PrivateRoute />}>
          <Route path="/change-password" element={<ChangePasswordPage />} />

          <Route element={<RoleRoute role="ADMIN" />}>
            <Route path="/admin/dashboard" element={shell(<AdminDashboard />)} />
            <Route path="/admin/patients" element={shell(<AdminPatients />)} />
            <Route path="/admin/doctors" element={shell(<AdminDoctors />)} />
            <Route path="/admin/appointments" element={shell(<AdminAppointments />)} />
            <Route path="/admin/recommendations" element={shell(<AdminRecommendations />)} />
            <Route path="/admin/access-requests" element={shell(<AdminAccessRequests />)} />
            <Route path="/admin/audit" element={shell(<AdminAudit />)} />
            <Route path="/admin/settings" element={shell(<AdminSettings />)} />
          </Route>

          <Route element={<RoleRoute role="DOCTOR" />}>
            <Route path="/doctor/dashboard" element={shell(<DoctorDashboard />)} />
            <Route path="/doctor/patients" element={shell(<DoctorPatients />)} />
            <Route path="/doctor/scan" element={shell(<DoctorScan />)} />
            <Route path="/doctor/appointments" element={shell(<DoctorAppointments />)} />
            <Route path="/doctor/profile" element={shell(<DoctorProfile />)} />
          </Route>

          <Route element={<RoleRoute role="PATIENT" />}>
            <Route path="/patient/dashboard" element={shell(<PatientDashboard />)} />
            <Route path="/patient/card" element={shell(<PatientCard />)} />
            <Route path="/patient/appointments" element={shell(<PatientAppointments />)} />
            <Route path="/patient/reports" element={shell(<PatientReports />)} />
            <Route path="/patient/find-care" element={shell(<PatientFindCare />)} />
            <Route path="/patient/profile" element={shell(<PatientProfile />)} />
          </Route>
        </Route>

        <Route path="/unauthorized" element={<Navigate to="/login" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  )
}
