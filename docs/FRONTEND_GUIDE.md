# Frontend build guide (READ FIRST — follow exactly)

Stack: React 19 + TS + Vite + Tailwind v4 (token-based) + shadcn-style components + framer-motion + @tanstack/react-query + sonner (toasts) + lucide-react. Path alias `@/` → `src/`.

## Non-negotiable conventions
- **Only use existing tokens & components.** Never hardcode hex colors. Use token classes: `bg-background surface surface-2 surface-3`, `text-foreground / text-muted-foreground / text-subtle-foreground`, `border-border / border-border-strong`, `bg-primary text-primary-foreground`, `bg-primary-soft text-primary-soft-foreground`, semantic `success/warning/danger/info` (each has `-soft`). Radii via `rounded-[var(--radius-md)]` etc. Shadows via `shadow-[var(--shadow-sm)]`.
- **Data fetching:** `@tanstack/react-query` (`useQuery`/`useMutation`). Wrap list/detail rendering in `<DataState isLoading isError isEmpty onRetry>`. Invalidate queries after mutations. Toasts: `import { toast } from 'sonner'` → `toast.success/error`.
- **Forms:** use `Field` (label+error) + `Input`/`Textarea`/`SimpleSelect`. Validate inline; show server errors via toast.
- **Every page** starts with `<PageHeader title description icon actions />`. Use `StatCard` for metrics, `EmptyState` for empties, `InfoRow` for profile details, `SectionTitle` for subsections.
- Display font (`font-display`) for big headings/numbers only. Body is default. Mono (`font-mono`) for IDs/codes.
- Keep motion subtle (framer-motion `initial/animate` fade-up, ~0.3s). Respect existing feel.
- TypeScript strict: `noUnusedLocals` ON — no unused imports. Type-only imports use `import type`.
- Do NOT edit files outside your assigned pages except to note routes needed. Do NOT touch `src/components/ui/*`, `src/lib/*`, `src/App.tsx`, `src/components/app-shell.tsx` (the integrator wires routes).

## Component inventory (import paths + key props)
- `@/components/ui/button` → `Button` (variant: primary|secondary|outline|ghost|soft|danger|link; size: sm|md|lg|icon|icon-sm; `loading`; `asChild` — when asChild the child MUST be a single element, no loader). 
- `@/components/ui/card` → `Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter`.
- `@/components/ui/input` → `Input, Textarea`.
- `@/components/ui/label` → `Label, Field` (`Field` props: label, htmlFor, hint, error, required, children).
- `@/components/ui/badge` → `Badge` (variant: neutral|primary|success|warning|danger|info|outline; `dot`).
- `@/components/ui/avatar` → `Avatar, AvatarImage, AvatarFallback, UserAvatar` (`UserAvatar name src className`).
- `@/components/ui/dialog` → `Dialog, DialogTrigger, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription, DialogClose`.
- `@/components/ui/dropdown-menu` → `DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem (destructive?), DropdownMenuLabel, DropdownMenuSeparator`.
- `@/components/ui/select` → `Select, SelectTrigger, SelectContent, SelectItem, SelectValue, SimpleSelect` (`SimpleSelect value onValueChange options placeholder` — options: string[] or {value,label}[]).
- `@/components/ui/tabs` → `Tabs, TabsList, TabsTrigger, TabsContent`.
- `@/components/ui/misc` → `Separator, Switch, Tooltip ({content,children,side}), Progress ({value}), Skeleton`.
- `@/components/patterns` → `PageHeader, StatCard ({label,value,icon,hint,tone,trend}), EmptyState ({icon,title,description,action}), DataState, ListSkeleton, StatCardSkeleton, InfoRow ({label,value,mono}), SectionTitle`.
- `@/components/status-badge` → `AppointmentStatusBadge ({status}), ActiveStatusBadge ({status}), AccessStatusBadge ({status})`.
- `@/components/brand` → `Logo, Wordmark`.
- `@/features/shared/SymptomChecker` → `SymptomChecker ({compact?, patientId?})` — full symptom→doctor recommender.
- Icons: `lucide-react`.
- Utils `@/lib/utils`: `cn, initials, formatBytes, formatDate, formatDateTime, timeAgo, formatTime`.

## Auth & session
- `@/lib/auth` → `useAuth()` → `{ user, role, loading, isAuthenticated, refresh, logout }`. `user` is CurrentUser (has `.patient_profile` / `.doctor_profile` when applicable, plus `id, username, email, first_name, last_name`).
- `@/lib/api` → `session` → `{ access, refresh, role, name, profileId, uuidToken, mustChangePassword }`.

## API services (`@/lib/api`) — all return parsed data (arrays already unwrapped from pagination)
- `authService`: login, verifyLoginOtp, me, changePassword, requestOtp/verifyOtp/resetWithOtp, adminStats(), adminResetPassword(user_id,new_password), listAdmins(), createAdmin(data).
- `patientService`: list(params), retrieve(id), create(FormData), update(id,FormData), remove(id), publicProfile(uuid), scan(uuid), qrUrl(id) → string, toggleStatus(id), resetPassword(id,new_password?), stats().
- `doctorService`: list(params), retrieve(id), create(FormData), update(id,FormData), remove(id), resetPassword(id,new_password?).
- `assignmentService`: list(params), create(doctor,patient), remove(id).
- `prescriptionService`: list(params), create({patient,diagnosis,medications,notes?}), update(id,data), remove(id).
- `recommendationService`: list(params), create({symptoms,pain_level,age,medical_history?,patient_id?}).
- `documentService`: list(params), upload(patientId,name,file,reportType), download(id)→Blob, remove(id).
- `appointmentService`: list(params), mine(params), forDoctor(params), stats(), create({doctor,appointment_date,appointment_time,reason?}), accept(id), decline(id), cancel(id), complete(id).
- `notificationService`: list(), markRead(id), markAllRead().
- `accessRequestService`: list(params), create(patient,reason?), approve(id), decline(id).
- `auditService`: list(params).
- `contactService`: send({name,email,subject,message}).

Types in `@/lib/types` (Patient, Doctor, Appointment, MedDocument, Prescription, Recommendation, Notification, AccessRequest, AuditLog, AdminStats, DoctorAssignment, etc.).

## API contract notes (match backend exactly)
- Patient/Doctor create/update use **FormData** (multipart) — build FormData with the model fields. Patient fields: first_name, middle_name, last_name, dob (YYYY-MM-DD), gender (Male/Female/Other), blood_group (A+,A-,B+,B-,AB+,AB-,O+,O-), phone & emergency_contact (Nepal `^(98|97)\d{8}$`, must differ), email (lowercase), address (5-255), height (30-250), weight (1-300), allergies, current_medication, status (Active/Inactive), photo (file). Server returns `generated_username`/`generated_password` on create — SHOW these once to admin.
- Doctor fields: first_name, last_name (map to user), license_number (unique), department (one of 21: General Medicine, Cardiology, Neurology, Dermatology, Pediatrics, Gynecology, Orthopedics, ENT, Ophthalmology, Psychiatry, Oncology, Urology, Gastroenterology, Nephrology, Endocrinology, Pulmonology, Emergency Medicine, Family Medicine, Dentistry, Radiology, Pathology), specialization, dob, gender, phone, email, status, availability_schedule (JSON: {Monday:"09:00-17:00", Tuesday:"closed", ...}), photo.
- Appointment lifecycle: PENDING → accept/decline; ACCEPTED → complete/cancel. Patient books (create) & cancels; doctor accepts/declines/completes.
- QR: `patientService.qrUrl(id)` returns an authenticated PNG URL (needs bearer) — for display, render a client QR with `react-qr-code` pointing to `${location.origin}/public-profile/${uuid_token}` instead (simpler, no auth needed). `react-qr-code` is installed: `import QRCode from 'react-qr-code'`.
- Documents: report_type MEDICAL (admin only) vs ADDITIONAL (patient can upload own). Validate file ≤5MB, ext pdf/png/jpg/jpeg. download() returns Blob → trigger browser download.
- Recommendation response includes `recommended_department, confidence, clinical_severity, reason, ranked_doctors[]` (each ranked doctor has score + reasons).

## Demo data exists (seeded). Backend runs at 127.0.0.1:8000, frontend proxies /api.
