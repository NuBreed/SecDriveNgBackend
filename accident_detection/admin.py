from django.contrib import admin

from accident_detection.models import (
    AccidentEvent, DeliveryLog, EmergencyEscalation, SOSRequest,
)


@admin.register(AccidentEvent)
class AccidentEventAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'journey', 'event_type', 'severity',
        'confirmation_status', 'detected_at',
    )
    list_filter = ('event_type', 'severity', 'confirmation_status')
    search_fields = ('journey__id',)
    readonly_fields = (
        'id', 'journey', 'event_type', 'severity',
        'latitude', 'longitude', 'acceleration_magnitude',
        'speed_before', 'speed_after', 'tilt_angle', 'rotation_rate',
        'raw_sensor', 'detected_at', 'confirmed_at', 'escalated_at',
        'countdown_task_id',
    )
    ordering = ('-detected_at',)


@admin.register(SOSRequest)
class SOSRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'journey', 'sos_type', 'status', 'triggered_at', 'retry_count')
    list_filter = ('sos_type', 'status')
    search_fields = ('journey__id', 'isafepass_sos_id')
    readonly_fields = (
        'id', 'journey', 'triggered_by', 'sos_type', 'status',
        'latitude', 'longitude', 'message', 'isafepass_sos_id',
        'response_data', 'triggered_at', 'delivered_at', 'retry_count',
    )
    ordering = ('-triggered_at',)


class DeliveryLogInline(admin.TabularInline):
    model = DeliveryLog
    extra = 0
    readonly_fields = (
        'attempt_number', 'success', 'http_status',
        'error', 'duration_ms', 'attempted_at',
    )
    can_delete = False


@admin.register(EmergencyEscalation)
class EmergencyEscalationAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'journey', 'escalation_type', 'status',
        'retry_count', 'created_at',
    )
    list_filter = ('escalation_type', 'status')
    search_fields = ('journey__id', 'isafepass_incident_id', 'isafepass_sos_id')
    readonly_fields = (
        'id', 'journey', 'accident_event', 'sos_request',
        'escalation_type', 'status',
        'isafepass_incident_id', 'isafepass_sos_id',
        'payload', 'response_data', 'error_message',
        'retry_count', 'max_retries', 'created_at', 'delivered_at', 'next_retry_at',
    )
    inlines = [DeliveryLogInline]
    ordering = ('-created_at',)


@admin.register(DeliveryLog)
class DeliveryLogAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'escalation', 'attempt_number', 'success',
        'http_status', 'duration_ms', 'attempted_at',
    )
    list_filter = ('success',)
    search_fields = ('escalation__id',)
    readonly_fields = (
        'id', 'escalation', 'attempt_number', 'success',
        'http_status', 'response_body', 'error', 'duration_ms', 'attempted_at',
    )
    ordering = ('-attempted_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
