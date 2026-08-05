from rest_framework import serializers
from apps.notifications.models import Notification

class NotificationSerializer(serializers.ModelSerializer):
    receiver_name = serializers.CharField(source='receiver.get_full_name', read_only=True)

    class Meta:
        model = Notification
        fields = (
            'id', 'receiver', 'receiver_name', 'role', 'title', 'message',
            'related_appointment', 'read', 'created_at'
        )
        read_only_fields = fields
