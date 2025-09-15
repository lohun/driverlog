# trips/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import Trip, Driver, ELDLog, RestStop
from .serializers import (
    TripSerializer, TripCreateSerializer, ELDLogSerializer,
    ELDLogCreateSerializer
)
from .services import RouteCalculatorService, ELDComplianceService
from re import fullmatch

class TripViewSet(viewsets.ModelViewSet):
    queryset = Trip.objects.all().select_related('driver__user').prefetch_related('rest_stops', 'eld_logs')
    serializer_class = TripSerializer
    log_serializer_class = ELDLogSerializer
    
    def get_serializer_class(self):
        if self.action == 'create':
            return TripCreateSerializer
        return TripSerializer
    
    def create(self, request):
        """Create a new trip and calculate route with ELD compliance"""
        serializer = TripCreateSerializer(data=request.data)
        if serializer.is_valid():
            driver, created = Driver.objects.get_or_create(
                id=1,
                defaults={
                    'user_id': 1,
                    'license_number': 'DEMO123',
                    'current_cycle_hours': serializer.validated_data['current_cycle_used_hours']
                }
            )
            
            trip = serializer.save(driver=driver)
            
            try:
                route_service = RouteCalculatorService()
                eld_service = ELDComplianceService()
                
                route_data = route_service.calculate_route(
                    current_location=trip.current_location,
                    pickup_location=trip.pickup_location,
                    dropoff_location=trip.dropoff_location
                )
                
                trip.route_coordinates = route_data['coordinates']
                trip.total_distance_miles = route_data['distance_miles']
                trip.estimated_drive_time_hours = route_data['duration_hours']
                trip.save()
                
                compliance_plan = eld_service.generate_compliance_plan(trip)
                
                for stop_data in compliance_plan['rest_stops']:
                    RestStop.objects.create(trip=trip, **stop_data)
                
                for log_data in compliance_plan['eld_logs']:
                    ELDLog.objects.create(trip=trip, driver=driver, **log_data)
                
                return Response(TripSerializer(trip).data, status=status.HTTP_201_CREATED)
                
            except Exception as e:
                return Response(
                    {'error': f'Route calculation failed: {str(e)}'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def eld_logs(self, request, pk=None):
        trip = self.get_object()
        logs = trip.eld_logs.all()
        serializer = ELDLogSerializer(logs, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def start_trip(self, request, pk=None):
        trip = self.get_object()
        trip.status = 'active'
        trip.trip_start_time = timezone.now()
        trip.save()
        
        return Response({'status': 'Trip started successfully'})
    
    @action(detail=True, methods=['post'])
    def end_trip(self, request, pk=None):
        trip = self.get_object()
        if trip.status == 'cancelled':
            return Response({"status": "Cannot complete a cancelled trip"}, status=status.HTTP_403_FORBIDDEN)
        trip.status = 'completed'
        trip.trip_end_time = timezone.now()
        trip.save()
        
        return Response({'status': 'Trip started successfully'})
    
    @action(detail=True, methods=['post'])
    def cancel_trip(self, request, pk=None):
        trip = self.get_object()
        if trip.status == 'completed':
            return Response({"status": "Cannot cancel trip"}, status=status.HTTP_403_FORBIDDEN)
        trip.status = 'cancelled'
        trip.trip_end_time = timezone.now()
        trip.save()
        
        return Response({'status': 'Trip cancelled successfully'})
    
    @action(detail=True, methods=['POST'])
    def add_log(self, request, pk=None):
        try:
            trip = self.get_object()
            driver = trip.driver

            serializer = ELDLogCreateSerializer(data=request.data)
            if serializer.is_valid():
                serializer.save(trip=trip, driver=driver)

            return Response(
                {"status": "Log added successfully"}, 
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
    @action(detail=False, methods=['post'])
    def geocode(self, request):
        address = request.data.get('address')
        if not address:
            return Response({'error': "Address is required"}, status=status.HTTP_400_BAD_REQUEST)
        # Restrictive regex: only letters, numbers, spaces, commas, periods, and hyphens
        if fullmatch(r"^[A-Za-z0-9\s,.\-]+$", address):
            # Dummy geocode result for demonstration; replace with actual geocoding logic
            geocode = {"lat": 0.0, "lng": 0.0, "address": address}
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Geocode result: {geocode}")
            return Response({'results': geocode})
        return Response({'status': "Address not found"}, status=status.HTTP_404_NOT_FOUND)

    