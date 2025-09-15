# trips/models.py
from django.db import models
from django.contrib.auth.models import User
from datetime import datetime, timedelta, time
import json

class Driver(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    license_number = models.CharField(max_length=50)
    current_cycle_hours = models.FloatField(default=0.0)
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.license_number}"

class Trip(models.Model):
    STATUS_CHOICES = [
        ('planned', 'Planned'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='trips')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')
    
    current_location = models.JSONField()
    pickup_location = models.JSONField()
    dropoff_location = models.JSONField()
    
    total_distance_miles = models.FloatField(null=True, blank=True)
    estimated_drive_time_hours = models.FloatField(null=True, blank=True)
    current_cycle_used_hours = models.FloatField()
    
    route_coordinates = models.JSONField(null=True, blank=True)
    waypoints = models.JSONField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    trip_start_time = models.DateTimeField(null=True, blank=True)
    trip_end_time = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Trip {self.id} - {self.driver.user.get_full_name()}"
    
    @property
    def requires_multiple_days(self):
        if not self.estimated_drive_time_hours:
            return False
        
        available_drive_hours = min(
            11,
            70 - self.current_cycle_used_hours
        )
        
        return self.estimated_drive_time_hours > available_drive_hours

class ELDLog(models.Model):
    DUTY_STATUS_CHOICES = [
        ('off_duty', 'Off Duty'),
        ('sleeper', 'Sleeper Berth'),
        ('driving', 'Driving'),
        ('on_duty', 'On Duty (Not Driving)'),
    ]
    
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='eld_logs', null=True, blank=True)
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE)
    
    log_date = models.DateField()
    duty_status = models.CharField(max_length=20, choices=DUTY_STATUS_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True)
    duration_hours = models.FloatField()
    
    location = models.JSONField(null=True, blank=True)
    
    remarks = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['log_date', 'start_time']
        # unique_together = [['driver', 'log_date', 'start_time']]
    
    def __str__(self):
        return f"{self.log_date} - {self.duty_status} ({self.duration_hours}h)"
    
    def clean(self):
        from django.core.exceptions import ValidationError
        
        if self.duration_hours <= 0:
            raise ValidationError('Duration must be positive')
        
        if self.duty_status == 'driving':
            daily_driving = ELDLog.objects.filter(
                driver=self.driver,
                log_date=self.log_date,
                duty_status='driving'
            ).exclude(pk=self.pk).aggregate(
                total=models.Sum('duration_hours')
            )['total'] or 0
            
            if daily_driving + self.duration_hours > 11:
                raise ValidationError('Daily driving limit of 11 hours exceeded')
        
        # if self.end_time:
        #     overlapping = ELDLog.objects.filter(
        #         driver=self.driver,
        #         log_date=self.log_date,
        #         start_time__lt=self.end_time,
        #         end_time__gt=self.start_time
        #     ).exclude(pk=self.pk)
            
        #     if overlapping.exists():
        #         raise ValidationError('Log entry overlaps with existing log')
    
    def save(self, *args, **kwargs):
        if not self.end_time and self.duration_hours:
            start_datetime = datetime.combine(self.log_date, self.start_time)
            end_datetime = start_datetime + timedelta(hours=self.duration_hours)
            
            if end_datetime.date() != self.log_date:
                self.end_time = time(23, 59, 59)  # End at day boundary
            else:
                self.end_time = end_datetime.time()
        
        self.clean()
        super().save(*args, **kwargs)
    
    @property
    def is_violation(self):
        """Check if this log creates any HOS violations"""
        # Check driving limits
        if self.duty_status == 'driving':
            daily_driving = ELDLog.objects.filter(
                driver=self.driver,
                log_date=self.log_date,
                duty_status='driving'
            ).aggregate(total=models.Sum('duration_hours'))['total'] or 0
            
            if daily_driving > 11:
                return True
        
        # Check on-duty limits
        daily_on_duty = ELDLog.objects.filter(
            driver=self.driver,
            log_date=self.log_date,
            duty_status__in=['driving', 'on_duty']
        ).aggregate(total=models.Sum('duration_hours'))['total'] or 0
        
        return daily_on_duty > 14

class RestStop(models.Model):
    STOP_TYPE_CHOICES = [
        ('fuel', 'Fuel Stop'),
        ('rest', 'Mandatory Rest'),
        ('break', '30-min Break'),
        ('pickup', 'Pickup Location'),
        ('dropoff', 'Dropoff Location'),
    ]
    
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='rest_stops')
    stop_type = models.CharField(max_length=20, choices=STOP_TYPE_CHOICES)
    
    # Location and timing
    location = models.JSONField()  # {"lat": float, "lng": float, "address": str}
    scheduled_arrival = models.DateTimeField()
    duration_hours = models.FloatField()
    
    # Distance from trip start
    distance_from_start_miles = models.FloatField()
    
    # HOS compliance
    is_mandatory = models.BooleanField(default=False)
    hos_reason = models.CharField(max_length=200, blank=True)  # Why this stop is needed
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['distance_from_start_miles']
    
    def __str__(self):
        return f"{self.stop_type} - {self.location.get('address', 'Unknown location')}"