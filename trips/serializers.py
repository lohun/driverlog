# trips/serializers.py
from rest_framework import serializers, validators
from .models import Driver, Trip, ELDLog, RestStop

class DriverSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    
    class Meta:
        model = Driver
        fields = ['id', 'full_name', 'license_number', 'current_cycle_hours']

class RestStopSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestStop
        fields = '__all__'

class ELDLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ELDLog
        fields = '__all__'

class TripSerializer(serializers.ModelSerializer):
    driver_info = DriverSerializer(source='driver', read_only=True)
    rest_stops = RestStopSerializer(many=True, read_only=True)
    eld_logs = ELDLogSerializer(many=True, read_only=True)
    
    class Meta:
        model = Trip
        fields = [
            'id', 'driver', 'driver_info', 'status',
            'current_location', 'pickup_location', 'dropoff_location',
            'total_distance_miles', 'estimated_drive_time_hours', 'current_cycle_used_hours',
            'route_coordinates', 'waypoints', 'rest_stops', 'eld_logs',
            'created_at', 'trip_start_time', 'trip_end_time', 'requires_multiple_days'
        ]

class TripCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = [
            'current_location', 'pickup_location', 'dropoff_location', 'current_cycle_used_hours'
        ]

class ELDLogCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ELDLog
        fields = [
            'log_date', 'duty_status', 'start_time', 'end_time', 'duration_hours', 'location', 'remarks'
        ]

class ELDLogUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ELDLog
        fields = "__all__"
