"""
Cycle calculator for ON/OFF pattern detection and ON hour accumulation
"""
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

class CyclePatterns:
    """Predefined cycle patterns for different UL/IEC standards"""
    
    PATTERNS = {
        "ul_8min_2min": {
            "name": "UL 8min ON / 2min OFF",
            "on_minutes": 8.0,
            "off_seconds": 120.0,
            "version": "UL",
            "description": "8 minutes ON, 2 minutes OFF cycle"
        },
        "iec_14min_30sec": {
            "name": "IEC 14min ON / 30sec OFF",
            "on_minutes": 14.0,
            "off_seconds": 30.0,
            "version": "IEC",
            "description": "14 minutes ON, 30 seconds OFF cycle"
        }
    }

class TimeSeriesAnalyzer:
    """Analyze time series data and calculate ON hours"""
    
    def __init__(self, pattern_key: str = "ul_8min_2min"):
        """Initialize with a specific cycle pattern"""
        self.pattern = CyclePatterns.PATTERNS.get(pattern_key, CyclePatterns.PATTERNS["ul_8min_2min"])
        self.on_duration = timedelta(minutes=self.pattern["on_minutes"])
        self.off_duration = timedelta(seconds=self.pattern["off_seconds"])
        self.cycle_duration = self.on_duration + self.off_duration
    
    def analyze_states(self, data_points: List[Dict]) -> Tuple[float, int]:
        """
        Analyze state transitions and calculate total ON hours and cycle count
        
        Args:
            data_points: List of dicts with 'timestamp' and 'state' ('ON'/'OFF')
        
        Returns:
            Tuple of (total_on_hours, number_of_cycles)
        """
        if not data_points or len(data_points) < 2:
            return 0.0, 0
        
        # Sort by timestamp
        sorted_points = sorted(data_points, key=lambda x: x['timestamp'])
        
        total_on_time = timedelta(0)
        cycle_count = 0
        
        # Process state transitions
        for i in range(len(sorted_points) - 1):
            current = sorted_points[i]
            next_point = sorted_points[i + 1]
            
            timestamp1 = self._parse_datetime(current['timestamp'])
            timestamp2 = self._parse_datetime(next_point['timestamp'])
            duration = timestamp2 - timestamp1
            
            # If current state is ON, accumulate the time
            if current['state'].upper() == 'ON':
                total_on_time += duration
            
            # Count complete cycles (ON + OFF)
            if (current['state'].upper() == 'OFF' and 
                next_point['state'].upper() == 'ON'):
                cycle_count += 1
        
        on_hours = total_on_time.total_seconds() / 3600.0
        return round(on_hours, 2), cycle_count
    
    def calculate_expected_on_hours(self, elapsed_time: timedelta) -> float:
        """
        Calculate expected ON hours based on elapsed time and pattern
        
        Args:
            elapsed_time: Total elapsed time
        
        Returns:
            Expected ON hours
        """
        if self.cycle_duration.total_seconds() == 0:
            return 0.0
        
        complete_cycles = elapsed_time / self.cycle_duration
        on_fraction = self.on_duration / self.cycle_duration
        
        expected_on_time = elapsed_time * on_fraction
        return expected_on_time.total_seconds() / 3600.0
    
    def get_cycle_info(self) -> Dict:
        """Get information about the current pattern"""
        return {
            "pattern_name": self.pattern["name"],
            "on_minutes": self.pattern["on_minutes"],
            "off_seconds": self.pattern["off_seconds"],
            "cycle_duration_seconds": self.cycle_duration.total_seconds(),
            "on_percentage": (self.on_duration / self.cycle_duration) * 100
        }
    
    @staticmethod
    def _parse_datetime(dt_value) -> datetime:
        """Parse datetime from various formats"""
        if isinstance(dt_value, datetime):
            return dt_value
        if isinstance(dt_value, str):
            # Try ISO format first
            try:
                return datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
            except:
                try:
                    return datetime.fromisoformat(dt_value)
                except:
                    return datetime.fromisoformat(dt_value)
        return dt_value

class OnHourAccumulator:
    """Accumulate ON hours across multiple uploads"""
    
    @staticmethod
    def calculate_cumulative_hours(previous_on_hours: float, new_data_points: List[Dict]) -> float:
        """
        Calculate cumulative ON hours from multiple data uploads
        
        Args:
            previous_on_hours: Previously accumulated ON hours
            new_data_points: New time series data points
        
        Returns:
            Total cumulative ON hours
        """
        analyzer = TimeSeriesAnalyzer()
        new_on_hours, _ = analyzer.analyze_states(new_data_points)
        return round(previous_on_hours + new_on_hours, 2)
    
    @staticmethod
    def calculate_progress(cumulative_on_hours: float, target_on_hours: int) -> float:
        """
        Calculate progress percentage
        
        Args:
            cumulative_on_hours: Accumulated ON hours
            target_on_hours: Target ON hours (468 or 500)
        
        Returns:
            Progress percentage (0-100)
        """
        if target_on_hours <= 0:
            return 0.0
        
        progress = (cumulative_on_hours / target_on_hours) * 100
        return min(round(progress, 2), 100.0)
