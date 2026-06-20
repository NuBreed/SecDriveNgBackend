from django.contrib import admin

from route_intelligence.models import (
    JourneyRisk, JourneyWarning, PlannedRoute, RouteDeviation, UnexpectedStop,
)


@admin.register(PlannedRoute)
class PlannedRouteAdmin(admin.ModelAdmin):
    list_display = ['id', 'journey', 'status', 'expected_duration_s',
                    'expected_distance_m', 'created_at']
    list_filter = ['status']
    search_fields = ['journey__id']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(RouteDeviation)
class RouteDeviationAdmin(admin.ModelAdmin):
    list_display = ['id', 'journey', 'deviation_type', 'severity',
                    'distance_from_route_m', 'is_resolved', 'timestamp']
    list_filter = ['deviation_type', 'severity', 'is_resolved']
    search_fields = ['journey__id']
    readonly_fields = ['id', 'timestamp']


@admin.register(UnexpectedStop)
class UnexpectedStopAdmin(admin.ModelAdmin):
    list_display = ['id', 'journey', 'started_at', 'ended_at',
                    'duration_s', 'is_unsafe_area', 'is_resolved']
    list_filter = ['is_unsafe_area', 'is_resolved']
    search_fields = ['journey__id']
    readonly_fields = ['id', 'started_at']


@admin.register(JourneyRisk)
class JourneyRiskAdmin(admin.ModelAdmin):
    list_display = ['id', 'journey', 'score', 'level', 'incident_created', 'last_updated']
    list_filter = ['level', 'incident_created']
    search_fields = ['journey__id']
    readonly_fields = ['id', 'last_updated']


@admin.register(JourneyWarning)
class JourneyWarningAdmin(admin.ModelAdmin):
    list_display = ['id', 'journey', 'warning_type', 'severity', 'is_resolved', 'created_at']
    list_filter = ['warning_type', 'severity', 'is_resolved']
    search_fields = ['journey__id', 'title']
    readonly_fields = ['id', 'created_at']
