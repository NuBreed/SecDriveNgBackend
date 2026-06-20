from django.contrib import admin

from journeys.models import Journey, JourneyEvent, JourneyLocation, JourneyShare, TrackingLink


class JourneyEventInline(admin.TabularInline):
    model = JourneyEvent
    extra = 0
    readonly_fields = ['id', 'event_type', 'actor', 'metadata', 'timestamp']
    can_delete = False


class JourneyLocationInline(admin.TabularInline):
    model = JourneyLocation
    extra = 0
    readonly_fields = ['id', 'latitude', 'longitude', 'speed', 'heading', 'timestamp']
    can_delete = False
    max_num = 20


@admin.register(Journey)
class JourneyAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'passenger', 'driver', 'vehicle', 'status',
        'created_at', 'started_at', 'completed_at',
    ]
    list_filter = ['status']
    search_fields = ['passenger__username', 'driver__license_number']
    readonly_fields = [
        'id', 'created_at', 'started_at', 'paused_at', 'completed_at', 'cancelled_at',
    ]
    inlines = [JourneyEventInline, JourneyLocationInline]


@admin.register(JourneyEvent)
class JourneyEventAdmin(admin.ModelAdmin):
    list_display = ['id', 'journey', 'event_type', 'actor', 'timestamp']
    list_filter = ['event_type']
    search_fields = ['journey__id']
    readonly_fields = ['id', 'timestamp']


@admin.register(JourneyShare)
class JourneyShareAdmin(admin.ModelAdmin):
    list_display = ['id', 'journey', 'contact', 'active', 'shared_at']
    list_filter = ['active']
    readonly_fields = ['id', 'shared_at']


@admin.register(TrackingLink)
class TrackingLinkAdmin(admin.ModelAdmin):
    list_display = ['id', 'journey', 'active', 'expires_at', 'created_at']
    readonly_fields = ['id', 'token', 'created_at']


@admin.register(JourneyLocation)
class JourneyLocationAdmin(admin.ModelAdmin):
    list_display = ['id', 'journey', 'latitude', 'longitude', 'speed', 'timestamp']
    search_fields = ['journey__id']
    readonly_fields = ['id', 'timestamp']
