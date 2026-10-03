from rest_framework import permissions

from apps.doctors.access import doctor_can_access


class IsReportOwner(permissions.BasePermission):
    """Patients act on their own reports; admins on any. Doctors with approved
    access may only read (retrieve, download, status)."""

    READ_ACTIONS = ('list', 'retrieve', 'download', 'status')

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if view.action in self.READ_ACTIONS:
            return True   # rows are limited in get_queryset
        if view.action == 'reprocess':
            return user.role == 'ADMIN'
        return user.role in ('ADMIN', 'PATIENT')

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.role == 'ADMIN':
            return True
        if user.role == 'PATIENT':
            return obj.patient.user_id == user.id
        if user.role == 'DOCTOR':
            return view.action in self.READ_ACTIONS and doctor_can_access(user, obj.patient)
        return False


class IsAdminReviewer(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == 'ADMIN')
