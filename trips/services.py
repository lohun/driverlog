import math
from datetime import datetime, timedelta, time, date
from django.conf import settings
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from openrouteservice import Client
from openrouteservice.directions import directions
from typing import Dict, List
from json import loads

class RouteCalculatorService:
    def __init__(self):
        self.base_url = "https://api.openrouteservice.org/v2/"
        self.api_key = settings.OPENROUTE_API_KEY
        self.geolocator = Nominatim(user_agent="eld_app")
    
    def geocode_address(self, address: str) -> Dict:
        try:
            location = self.geolocator.geocode(address)
            print(location)
            if location:
                return {
                    'lat': location.latitude,
                    'lng': location.longitude,
                }
        except Exception as e:
            print(f"Geocoding error: {e}")
        
        return None
    
    def calculate_route(self, current_location: Dict, pickup_location: Dict, dropoff_location: Dict) -> Dict:
        client = Client(key=self.api_key)
        start_coords = (current_location['lng'], current_location['lat'])
        pickup_coords = (pickup_location['lng'], pickup_location['lat'])
        drop_coords = (dropoff_location['lng'], dropoff_location['lat'])
        coords = [start_coords, pickup_coords, drop_coords]
        try:
            response = directions(client=client, coordinates=coords, profile="driving-hgv", format="geojson", instructions=True, elevation=True, units='mi')
            if response:
                data = loads(response)
                route = data['features'][0]
                
                # Extract route information
                properties = route['properties']
                coordinates = route['geometry']['coordinates']
                
                # Convert to lat, lng format for frontend
                route_coordinates = [[coord[1], coord[0]] for coord in coordinates]
                
                return {
                    'coordinates': route_coordinates,
                    'distance_miles': properties['segments'][0]['distance'],  
                    'duration_hours': properties['segments'][0]['duration'],
                    'instructions': self._parse_instructions(properties['segments'][0]['steps'])
                }
        except Exception as e:
            print(f"Route Calculation error: {e}")
        
        return self._calculate_fallback_route(current_location, pickup_location, dropoff_location)
    
    def _calculate_fallback_route(self, current: Dict, pickup: Dict, dropoff: Dict) -> Dict:
        """Fallback route calculation using straight-line distance"""
        
        # Calculate distances
        current_to_pickup = geodesic(
            (current['lat'], current['lng']), 
            (pickup['lat'], pickup['lng'])
        ).miles
        
        pickup_to_dropoff = geodesic(
            (pickup['lat'], pickup['lng']), 
            (dropoff['lat'], dropoff['lng'])
        ).miles
        
        total_distance = current_to_pickup + pickup_to_dropoff
        
        # Estimate driving time (average 55 mph for trucks)
        estimated_hours = total_distance / 55
        
        # Create simple route coordinates
        route_coordinates = [
            [current['lat'], current['lng']],
            [pickup['lat'], pickup['lng']],
            [dropoff['lat'], dropoff['lng']]
        ]
        
        return {
            'coordinates': route_coordinates,
            'distance_miles': total_distance,
            'duration_hours': estimated_hours,
            'instructions': [
                f"Drive {current_to_pickup:.1f} miles to pickup location",
                f"Drive {pickup_to_dropoff:.1f} miles to dropoff location"
            ]
        }
    
    def _parse_instructions(self, steps: List) -> List[str]:
        """Parse route instructions from API response"""
        instructions = []
        for step in steps:
            if 'instruction' in step:
                distance_miles = step['distance'] * 0.000621371
                instructions.append(f"{step['instruction']} ({distance_miles:.1f} miles)")
        return instructions

class ELDComplianceService:
    # HOS Rules (Property-carrying drivers)
    MAX_DRIVING_HOURS_DAILY = 11
    MAX_ON_DUTY_HOURS_DAILY = 14
    MAX_CYCLE_HOURS = 70  # 8-day cycle
    MANDATORY_BREAK_HOURS = 0.5  # 30-minute break after 8 hours
    MIN_OFF_DUTY_HOURS = 10  # Between shifts
    
    def generate_compliance_plan(self, trip) -> Dict:
        total_drive_hours = trip.estimated_drive_time_hours
        pickup_dropoff_hours = 2.0  # 1 hour each for pickup/dropoff
        total_on_duty_hours = total_drive_hours + pickup_dropoff_hours
        
        # Calculate how many days the trip will take
        available_drive_hours = min(
            self.MAX_DRIVING_HOURS_DAILY,
            self.MAX_CYCLE_HOURS - trip.current_cycle_used_hours
        )
        
        days_required = math.ceil(total_drive_hours / available_drive_hours)
        
        # Generate day-by-day plan
        rest_stops = []
        eld_logs = []
        current_date = date.today()
        
        remaining_drive_hours = total_drive_hours
        distance_covered = 0
        
        for day in range(days_required):
            day_date = current_date + timedelta(days=day)
            
            # Calculate hours for this day
            if day == 0:
                # First day: account for current cycle usage
                daily_drive_hours = min(
                    remaining_drive_hours,
                    self.MAX_DRIVING_HOURS_DAILY,
                    max(0, self.MAX_CYCLE_HOURS - trip.current_cycle_used_hours)
                )
            else:
                daily_drive_hours = min(remaining_drive_hours, self.MAX_DRIVING_HOURS_DAILY)
            
            # Generate ELD logs for this day
            day_logs = self._generate_daily_logs(day_date, daily_drive_hours, day == 0)
            eld_logs.extend(day_logs)
            
            # Calculate rest stops for this day
            if daily_drive_hours > 8:
                # Need 30-minute break
                distance_for_break = (distance_covered + 
                                    (8 / total_drive_hours) * trip.total_distance_miles)
                
                rest_stops.append({
                    'stop_type': 'break',
                    'location': self._interpolate_location(
                        trip.route_coordinates, 
                        distance_for_break / trip.total_distance_miles
                    ),
                    'scheduled_arrival': datetime.combine(
                        day_date, 
                        time(12, 0)  # Approximate break time
                    ),
                    'duration_hours': 0.5,
                    'distance_from_start_miles': distance_for_break,
                    'is_mandatory': True,
                    'hos_reason': '30-minute break required after 8 hours driving'
                })
            
            # Add fuel stop if needed (every 1000 miles)
            if distance_covered > 0 and distance_covered % 1000 < 200:
                rest_stops.append({
                    'stop_type': 'fuel',
                    'location': self._interpolate_location(
                        trip.route_coordinates, 
                        distance_covered / trip.total_distance_miles
                    ),
                    'scheduled_arrival': datetime.combine(day_date, time(18, 0)),
                    'duration_hours': 0.5,
                    'distance_from_start_miles': distance_covered,
                    'is_mandatory': False,
                    'hos_reason': 'Fuel stop (1000+ miles)'
                })
            
            remaining_drive_hours -= daily_drive_hours
            distance_covered += (daily_drive_hours / total_drive_hours) * trip.total_distance_miles
            
            # Add mandatory rest if more days needed
            if remaining_drive_hours > 0:
                rest_stops.append({
                    'stop_type': 'rest',
                    'location': self._interpolate_location(
                        trip.route_coordinates, 
                        distance_covered / trip.total_distance_miles
                    ),
                    'scheduled_arrival': datetime.combine(day_date, time(22, 0)),
                    'duration_hours': 10,
                    'distance_from_start_miles': distance_covered,
                    'is_mandatory': True,
                    'hos_reason': f'Mandatory 10-hour rest before day {day + 2}'
                })
        
        return {
            'rest_stops': rest_stops,
            'eld_logs': eld_logs,
            'total_days': days_required,
            'compliance_summary': {
                'total_drive_hours': total_drive_hours,
                'total_on_duty_hours': total_on_duty_hours,
                'days_required': days_required,
                'cycle_hours_used': trip.current_cycle_used_hours + total_on_duty_hours
            }
        }
    
    def _generate_daily_logs(self, log_date: date, drive_hours: float, is_first_day: bool) -> List[Dict]:
        """Generate ELD logs for a single day"""
        logs = []
        
        if is_first_day:
            # Start with current status
            logs.append({
                'log_date': log_date,
                'duty_status': 'on_duty',
                'start_time': time(6, 0),
                'duration_hours': 1.0,  # Pre-trip inspection
                'remarks': 'Pre-trip inspection and trip planning'
            })
        else:
            # Previous day off-duty period
            logs.append({
                'log_date': log_date,
                'duty_status': 'off_duty',
                'start_time': time(0, 0),
                'duration_hours': 10.0,
                'remarks': 'Required 10-hour off-duty period'
            })
        
        # Driving periods
        start_hour = 7 if is_first_day else 10
        
        if drive_hours <= 8:
            # Can drive continuously
            logs.append({
                'log_date': log_date,
                'duty_status': 'driving',
                'start_time': time(start_hour, 0),
                'duration_hours': drive_hours,
                'remarks': 'Driving to destination'
            })
        else:
            # Need break after 8 hours
            logs.append({
                'log_date': log_date,
                'duty_status': 'driving',
                'start_time': time(start_hour, 0),
                'duration_hours': 8.0,
                'remarks': 'Driving (first 8 hours)'
            })
            
            # Mandatory break
            logs.append({
                'log_date': log_date,
                'duty_status': 'off_duty',
                'start_time': time(start_hour + 8, 0),
                'duration_hours': 0.5,
                'remarks': 'Mandatory 30-minute break'
            })
            
            # Continue driving
            logs.append({
                'log_date': log_date,
                'duty_status': 'driving',
                'start_time': time(start_hour + 8, 30),
                'duration_hours': drive_hours - 8,
                'remarks': 'Driving (after break)'
            })
        
        return logs
    
    def _interpolate_location(self, route_coordinates: List, progress: float) -> Dict:
        """Find location along route at given progress (0.0 to 1.0)"""
        if not route_coordinates or progress <= 0:
            return {
                'lat': route_coordinates[0][0] if route_coordinates else 0,
                'lng': route_coordinates[0][1] if route_coordinates else 0,
                'address': 'Route location'
            }
        
        if progress >= 1.0:
            return {
                'lat': route_coordinates[-1][0],
                'lng': route_coordinates[-1][1],
                'address': 'Route location'
            }
        
        # Simple interpolation
        index = int(progress * (len(route_coordinates) - 1))
        coord = route_coordinates[index]
        
        return {
            'lat': coord[0],
            'lng': coord[1],
            'address': f'Mile marker {int(progress * 1000)}'
        }