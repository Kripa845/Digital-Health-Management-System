from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth import get_user_model

from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer

User = get_user_model()

class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Notification.objects.filter(receiver=user).order_by('-created_at')

    def create(self, request, *args, **kwargs):
        return Response({'detail': 'Notifications are created automatically by the system.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.read = True
        notification.save(update_fields=['read'])
        return Response({'status': 'ok'})

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        qs = Notification.objects.filter(receiver=request.user, read=False)
        updated = qs.update(read=True)
        return Response({'status': 'ok', 'updated': updated})
