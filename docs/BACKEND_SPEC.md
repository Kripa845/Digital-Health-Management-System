# Mero Care Card — Backend Rebuild Specification

Django 6.0.7 + DRF 3.17.1 + SimpleJWT 5.5.1. Project package `config`, apps under `apps/`.
Custom user model `users.User`. All API routes prefixed `/api/v1/`.

## 1. Django Apps
- `apps.users`: custom `User` (roles + `must_change_password`), auth (login + email 2FA OTP, JWT refresh, `/me`, change-password, forgot-password 3-step OTP), admin tools (stats, manage-admins, reset-password), contact form, `PasswordResetOTP`, permission classes, credential emails, admin-seed signal.
- `apps.patients`: `Patient` profile with auto card ID + `uuid_token`, CRUD (admin writes), QR PNG, public QR profile (identifier-only), authenticated doctor "scan", toggle status, admin password reset, stats.
- `apps.doctors`: `Doctor` (license, department, availability schedule), `DoctorAssignment`, `AccessRequest`, `Prescription`.
- `apps.recommendations`: `RecommendationHistory` + rule-based engine. Data files drive rules.
- `apps.documents`: `Document` (MEDICAL vs ADDITIONAL), upload/download with per-role object perms.
- `apps.audit`: `AuditLog` append-only; admin read API; `log_activity()` helper.
- `apps.appointments`: `Appointment` (UUID PK), PENDING→ACCEPTED/DECLINED→COMPLETED/CANCELLED state machine, notifications on transitions.
- `apps.notifications`: `Notification` per-user, role-tagged; list + mark-read/mark-all-read.

## 2. Models (exact fields)

### users.User (AbstractUser)
- `role` CharField(10, choices ADMIN/DOCTOR/PATIENT, default PATIENT)
- `must_change_password` BooleanField(default=False)
- `__str__` = "{username} ({role})". `AUTH_USER_MODEL='users.User'`.

### users.PasswordResetOTP
Constants OTP_TTL_MINUTES=10, MAX_ATTEMPTS=5. Purpose choices RESET/LOGIN.
- user FK CASCADE related_name='reset_otps'
- purpose CharField(10, default RESET, db_index)
- code CharField(6); created_at auto_now_add; expires_at DateTime; is_used bool; attempts PositiveInt(0)
- Meta index (user,purpose,-created_at); ordering -created_at
- classmethod issue(user, purpose=RESET): invalidate prior unused, code=f"{secrets.randbelow(10**6):06d}", expires now+10min
- is_valid(): not used AND attempts<5 AND now<expires_at

### patients.Patient
- user O2O CASCADE related_name='patient_profile'
- patient_id CharField(15, unique, editable=False, db_index). Format `PAT-`+first 8 hex of uuid4().hex uppercased
- uuid_token UUIDField(default=uuid4, unique, editable=False)
- first_name(50), middle_name(50 blank null), last_name(50)
- dob DateField; gender(10 Male/Female/Other); blood_group(5 A+,A-,B+,B-,AB+,AB-,O+,O-)
- phone(15), emergency_contact(15), email(EmailField blank null), address TextField
- height/weight DecimalField(5,2)
- allergies/current_medication/prescription/pain_log TextField(blank null)
- status(10 Active/Inactive default Active)
- photo ImageField(upload_to='patient_photos/', blank null)
- registration_date auto_now_add; created_by FK User SET_NULL null related_name='created_patients'; last_updated auto_now
- @property age; classmethod generate_patient_id() 10 retries; save() assigns id if blank

### doctors.Doctor
- user O2O CASCADE related_name='doctor_profile'
- doctor_id CharField(15 unique editable=False db_index). Format `DOC-`+8 upper hex
- uuid_token UUIDField(unique, editable=False, db_index) — NO default, set in save()
- license_number CharField(50 unique)
- department CharField(50 choices) — 21: General Medicine, Cardiology, Neurology, Dermatology, Pediatrics, Gynecology, Orthopedics, ENT, Ophthalmology, Psychiatry, Oncology, Urology, Gastroenterology, Nephrology, Endocrinology, Pulmonology, Emergency Medicine, Family Medicine, Dentistry, Radiology, Pathology
- specialization(100); dob DateField; gender(10); phone(15); email EmailField
- photo ImageField(upload_to='doctor_photos/', blank null)
- status(10 Active/Inactive default Active)
- availability_schedule JSONField(default=dict). Shape {"Monday":"09:00-17:00","Tuesday":"closed",...} keyed by %A. Available if value non-empty and not "closed" (ci). Empty dict = always available.
- registration_date auto_now_add; @property age; classmethod generate_doctor_id() 10 retries; save() sets doctor_id+uuid_token if blank

### doctors.DoctorAssignment
- doctor FK CASCADE related_name='assignments'; patient FK CASCADE related_name='assignments'
- assigned_date auto_now_add; status(15 Active/Inactive default Active). Uniqueness enforced in serializer.

### doctors.AccessRequest
STATUS PENDING/APPROVED/DECLINED.
- doctor FK CASCADE related_name='access_requests'; patient FK CASCADE related_name='access_requests'
- status(10 default PENDING db_index); reason TextField blank null; created_at auto_now_add db_index
- resolved_at DateTime null blank; resolved_by FK User SET_NULL null blank related_name='resolved_access_requests'
- Meta ordering -created_at; index (status,-created_at)

### doctors.Prescription
- patient FK CASCADE related_name='prescriptions'; doctor FK **User** CASCADE related_name='issued_prescriptions'
- diagnosis TextField; medications TextField; notes TextField blank null; prescription_date auto_now_add db_index
- Meta indexes (patient,-date),(doctor,-date); ordering -prescription_date

### recommendations.RecommendationHistory
- patient FK SET_NULL null blank related_name='recommendation_history'
- symptoms TextField; pain_level Int validators Min1 Max10; age Int blank null Min1 Max120; medical_history TextField blank null
- recommended_doctor FK Doctor SET_NULL null blank related_name='recommendations'
- recommended_department(50); score FloatField blank null; confidence Int blank null; reason TextField blank null
- recommendation_date auto_now_add db_index; Meta indexes (-date),(patient,-date),(dept,-date)

### documents.Document
REPORT_TYPE MEDICAL='Medical Report', ADDITIONAL='Additional Report'.
- patient FK CASCADE related_name='documents'; file FileField(upload_to='patient_documents/', validators=[validate ext+size])
- name(255); file_type(10 blank auto upper ext); size Int blank null (bytes); uploaded_at auto_now_add
- report_type(10 default ADDITIONAL); uploaded_by FK User SET_NULL null blank related_name='uploaded_documents'
- validator: ext in .pdf/.png/.jpg/.jpeg, size<=5MB. save() sets size, file_type, name

### audit.AuditLog
- user FK SET_NULL null blank related_name='audit_logs'; action(50 db_index); description TextField; timestamp auto_now_add db_index; ip_address GenericIPAddress blank null
- Meta indexes (-timestamp,action),(user,-timestamp); log_activity(user,action,description,request) helper (IP from X-Forwarded-For or REMOTE_ADDR)

### appointments.Appointment
STATUS PENDING/ACCEPTED/DECLINED/COMPLETED/CANCELLED.
- id UUIDField pk default uuid4 editable=False
- patient FK CASCADE related_name='appointments'; doctor FK CASCADE related_name='appointments'
- appointment_date DateField; appointment_time TimeField; status(20 default PENDING db_index)
- reason/notes TextField blank null; created_at auto_now_add db_index; updated_at auto_now
- approved_by FK User SET_NULL null blank related_name='approved_appointments'; completed_at/cancelled_at DateTime null blank
- Meta indexes (patient,date,status),(doctor,date,status),(status,date); ordering -date,-time
- State machine: create=PENDING; accept PENDING→ACCEPTED (approved_by); decline PENDING→DECLINED; cancel PENDING|ACCEPTED→CANCELLED (cancelled_at); complete ACCEPTED→COMPLETED (completed_at). Invalid transitions 400.

### notifications.Notification
ROLE ADMIN/DOCTOR/PATIENT.
- id UUIDField pk default uuid4; receiver FK CASCADE related_name='notifications'; role(10); title(255); message TextField
- related_appointment FK SET_NULL null blank related_name='notifications'; read bool db_index; created_at auto_now_add db_index
- Meta indexes (receiver,-created_at),(role,read,-created_at); ordering -created_at

## 3. Recommendation Engine (apps/recommendations/views.py)
Data: data/symptom_department_map.json (keys department_rules {dept:{keyword:weight}} weights 3=defining/2=related/1=generic; department_equivalences {kw:[depts]}), data/symptom_severity.csv (Symptom,weight ~133 rows 1-7). Load once into DEPARTMENT_RULES, DEPARTMENT_EQUIVALENCES, SYMPTOM_SEVERITY. _MAX_SEVERITY=7.

- clinical_severity_index(symptoms)->0..100: lower text; match if name.replace('_',' ') substring; none→0 else round(100*max_weight/7)
- score_departments(symptoms, medical_history='')->{dept:float}: +weight per keyword substring in symptoms; +weight*0.5 per keyword in history. Keep dept if total>0. Empty→API 400.
- match_department: max score dept else 'General Medicine'
- department_confidence(scores, primary)->int: no scores→40; else round(100*top/sum) clamped [25,98]
- age_fit(dept, age)->(pts, reason): None→(0,None); Pediatrics age<=14→(15,"patient age suits Pediatrics"); age<=14 and dept in {General Medicine,Family Medicine}→(8,"general care appropriate for a young patient"); age>=60 and dept in {Cardiology,General Medicine,Endocrinology,Nephrology,Neurology}→(10,"age is a relevant risk factor for this department"); else (6,None)
- score_doctor(doctor, ctx)->(round(score,2), reasons): ctx={dept_scores, top_dept_score, age, pain_level, history_lower}
  1. Match 0-50: dept_raw=dept_scores.get(dept,0); if top>0 match_pts=50*dept_raw/top else 0; reason if dept_raw>0 "symptoms match {dept}"
  2. History +15: if history and any dept keyword in history → +15 "medical history relates to {dept}"
  3. Age: +age_pts, append reason if present
  4. Pain 0-10: only if dept_raw>0: +pain (pain=ctx pain_level or 0); if pain>=8 "high pain level ({pain}/10) prioritised"
  5. Availability +5 if is_doctor_available "available today"
  6. Caseload: active_load=assignments filter status Active count; +5/(1+active_load); if 0 "no current caseload"
  is_doctor_available: empty schedule=True; else today %A slot non-empty and not "closed"
- build_recommendation(symptoms, pain_level, age, medical_history)->dict:
  compute dept_scores, primary_dept, confidence, severity. candidate_depts = dept_scores keys + get_equivalenced_depts (starts [primary] + depts whose equivalence kw substring of symptoms), dedup. candidates=Doctor.filter(department__in=candidates, status=Active). Fallback: General Medicine active; then all active. Score each. Sort by (score desc, active_load asc). escalate = pain>=8 or severity>=70; limit=2 if escalate else 3; ranked=scored[:limit]. Build reason string (see spec variants). Returns {department, confidence, primary, score, reason, clinical_severity, ranked}
- POST create persists RecommendationHistory (patient=requester's if PATIENT; admin optional patient_id; guest null), serializes + adds clinical_severity + ranked_doctors (DoctorSerializer + score + reasons)

## 4. API Endpoints (base /api/v1/, JWT Bearer default, IsAuthenticated default, PageNumber page 10; Appointments no pagination)

### Auth (config/urls + users)
- POST /auth/login/ (none) {username,password}: if user has email → issue LOGIN OTP, email, return {otp_required:true, identifier, email_hint, detail}; no email → full login payload + otp_required:false. 401 bad creds; 503 OTP email fail
- POST /auth/login/verify-otp/ (none) {identifier,code} → login payload
- POST /auth/token/refresh/ (AllowAny) {refresh} → {access,refresh} rotate+blacklist
- GET /auth/me/ (auth) → UserSerializer + nested doctor_profile/patient_profile
- POST /auth/change-password/ (auth) {old_password,new_password} → {message}; clears must_change_password
- POST /auth/forgot-password/request-otp/ (AllowAny throttle otp 10/hr) {identifier} → generic {message}
- POST /auth/forgot-password/verify-otp/ (AllowAny) {identifier,code} → {valid:true}|400
- POST /auth/forgot-password/reset/ (AllowAny) {identifier,code,new_password} → {message}
- POST /auth/admin/reset-password/ (IsAdmin) {user_id,new_password} → {message}; target must_change_password=True; can't target ADMIN
- GET/POST /auth/admin/manage-admins/ (IsAdmin) list ADMINs / create ADMIN {username,email,first_name,last_name,password}
- GET /auth/admin/stats/ (IsAdmin) → {total_users,total_patients,total_doctors,total_admins,today_registrations,active_users,inactive_users,recent_patients[5],recent_doctors[5],registration_chart[7]}
- POST /contact/ (AllowAny throttle contact 20/hr) {name,email,subject,message} → {detail}
Login payload: {access,refresh,role,username,first_name,last_name,must_change_password} + DOCTOR profile_id(doctor_id); PATIENT profile_id(patient_id)+uuid_token. JWT claims: role,username,first_name,last_name,profile_id,(patient)uuid_token.

### Patients /patients/
- GET list (auth, scoped: ADMIN all; DOCTOR active-assigned; PATIENT self) filters status,blood_group,registration_date; search names,patient_id,phone,allergies,current_medication; order patient_id,registration_date,last_updated
- POST (IsAdmin) creates User(PATIENT, must_change=True)+Patient, auto username = name-based `firstname.lastname` (unique, numeric suffix on collision; falls back to card id) + random pw unless provided, emails creds, response + generated_username/generated_password/credentials_emailed/email
- GET/PUT/PATCH/DELETE {id} (PUT/PATCH/DELETE IsAdmin; PATCH syncs first/last/email to User; DELETE removes User cascade)
- GET /patients/public/{uuid}/ (AllowAny) identifier-only public card
- GET /patients/{id}/qr/ (auth) PNG QR → {FRONTEND_URL}/public-profile/{uuid_token}
- GET /patients/scan/{uuid}/ (auth doctor/admin) FULL if admin/active-assigned else GENERAL minimal
- PATCH /patients/{id}/toggle_status/ (IsAdmin)
- POST /patients/{id}/reset_password/ (IsAdmin) → {patient_id,username,new_password,message}
- GET /patients/stats/ (IsAdmin)
PatientSerializer validations: names letters 2-50; dob not future age<=120; phone/emergency ^(98|97)\d{8}$ differ; address 5-255; email lowercase; height 30-250; weight 1-300.

### Doctors /doctors/
- GET list/retrieve (auth all visible); POST (IsAdmin creates User DOCTOR+emails); PUT/PATCH (IsAdminOrSelfDoctor, non-admin can't change status); DELETE (IsAdmin); POST {id}/reset_password/ (IsAdmin)
filters status,department,gender; search user names,doctor_id,uuid_token,license_number,specialization,phone. availability_schedule accepts JSON string or dict.

### Assignments /assignments/ CRUD (writes IsAdmin, reads auth scoped) filters status,doctor,patient; reject dup
### Access Requests /access-requests/ (get,post only)
- GET (auth ADMIN all; DOCTOR own); POST (IsDoctor {patient,reason} reject if assigned/pending; notify admins); POST {id}/approve/ (IsAdmin →APPROVED create/activate assignment notify doctor); POST {id}/decline/ (IsAdmin →DECLINED notify)
### Prescriptions /prescriptions/ CRUD (writes IsDoctorOrAdmin, reads auth scoped) doctor=request.user on create; DOCTOR only for active-assigned patient; filters patient,doctor
### Recommendations /recommendations/ POST AllowAny (engine); GET auth scoped
### Documents /documents/ DocumentPermission: reads scoped; create MEDICAL→admin, ADDITIONAL→admin/patient(own); update/destroy admin(MEDICAL)/patient(own ADDITIONAL); GET {id}/download/ attachment; filters patient,report_type
### Audit /audit-logs/ ReadOnly IsAdmin filters action,user; search description,action,user__username,ip_address; order timestamp
### Appointments /appointments/ AppointmentPermission no pagination; scoped; POST patient auto; my/, doctor/, stats/; {id}/accept|decline|cancel|complete/; validate no past, no double-book
### Notifications /notifications/ reads own; POST 405; {id}/mark-read/; mark-all-read/ →{updated}

## 5. Permissions (apps/users/permissions.py)
IsAdmin, IsDoctor, IsPatient, IsDoctorOrAdmin, IsAdminOrSelfDoctor (obj: ADMIN always; DOCTOR if obj.user==request.user). DocumentPermission, AppointmentPermission inline. Layered: get_permissions + get_queryset scoping + object perms.

## 6. Auth specifics
SIMPLE_JWT: access 60min, refresh 7 days, ROTATE+BLACKLIST True, HS256, SIGNING_KEY=SECRET_KEY, Bearer. token_blacklist installed. Refresh public.
Login = mandatory email 2FA when user has email (LOGIN OTP), else skip. OTP 6-digit, TTL 10min, max 5, one active per user+purpose.
Admin-created accounts: name-based usernames via `apps/users/username.py` — patient `firstname.lastname`, doctor `dr.lastname` (accent-stripped, `.`-joined, numeric suffix on collision, card-id fallback); admin may override with a custom `username`. Random pw _generate_password(10) 10 chars ascii_letters+digits regenerated until has upper+lower+digit; must_change_password=True; email creds (skip if '[PROVIDED]'). 
QR privacy: /qr/ PNG encodes public-profile URL; public/{uuid} identifier-only; scan/{uuid} FULL vs GENERAL by assignment.

## 7. Settings
Apps: contrib + rest_framework, simplejwt, token_blacklist, corsheaders, django_filters, cloudinary_storage, cloudinary + 8 project apps.
Middleware: Security, WhiteNoise, Sessions, CORS(before Common), Common, CSRF, Auth, Messages, XFrame.
DRF: JWTAuthentication only; IsAuthenticated default; DjangoFilter+Search+Ordering; PageNumber PAGE_SIZE=10; throttle anon 100/day user 1000/day otp 10/hr contact 20/hr.
DB: dj_database_url default sqlite, conn_max_age 600. AUTH_USER_MODEL='users.User'; password validator MinLength 8 (letters+digits in serializers).
CORS: env list or allow-all dev. Cloudinary if 3 env vars else FileSystem. WhiteNoise static.
Email: Anymail Brevo/SendGrid → SMTP → console. TIME_ZONE Asia/Kathmandu, USE_TZ. FRONTEND_URL env. healthz/ probe. Admin-seed post_migrate from DJANGO_ADMIN_* when DJANGO_ADMIN_PASSWORD set.
