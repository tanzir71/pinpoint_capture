"""Data models for Pinpoint Capture screen recorder application."""

from dataclasses import dataclass
from typing import Tuple, Optional
import time


@dataclass
class ClickEvent:
    """Represents a mouse click event during recording."""
    timestamp: float
    x: int
    y: int
    button: str  # 'left', 'right', 'middle'
    screen_resolution: Tuple[int, int]
    
    @classmethod
    def create_now(cls, x: int, y: int, button: str, screen_resolution: Tuple[int, int]) -> 'ClickEvent':
        """Create a ClickEvent with current timestamp."""
        return cls(
            timestamp=time.time(),
            x=x,
            y=y,
            button=button,
            screen_resolution=screen_resolution
        )


@dataclass
class RecordingSettings:
    """Configuration settings for recording session."""
    resolution: Tuple[int, int] = (1920, 1080)  # (width, height)
    fps: int = 30  # frames per second
    zoom_level: float = 2.0  # 1.5 to 5.0
    zoom_duration: float = 3.0  # 1.0 to 10.0 seconds
    transition_speed: float = 1.0  # 0.1 to 2.0
    output_format: str = 'mp4'  # 'mp4', 'avi'
    output_path: str = './recordings'
    auto_save: bool = True
    compression_quality: int = 85  # 0-100
    click_detection_sensitivity: float = 0.5  # 0.1-1.0
    record_mic: bool = False  # Enable microphone recording
    mic_device_id: Optional[int] = None  # Microphone device ID
    
    def to_dict(self) -> dict:
        """Convert settings to dictionary for JSON serialization."""
        return {
            'resolution': list(self.resolution),
            'fps': self.fps,
            'zoom_level': self.zoom_level,
            'zoom_duration': self.zoom_duration,
            'transition_speed': self.transition_speed,
            'output_format': self.output_format,
            'output_path': self.output_path,
            'auto_save': self.auto_save,
            'compression_quality': self.compression_quality,
            'click_detection_sensitivity': self.click_detection_sensitivity,
            'record_mic': self.record_mic,
            'mic_device_id': self.mic_device_id
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RecordingSettings':
        """Create RecordingSettings from dictionary."""
        return cls(
            resolution=tuple(data.get('resolution', [1920, 1080])),
            fps=data.get('fps', 30),
            zoom_level=data.get('zoom_level', 2.0),
            zoom_duration=data.get('zoom_duration', 3.0),
            transition_speed=data.get('transition_speed', 1.0),
            output_format=data.get('output_format', 'mp4'),
            output_path=data.get('output_path', './recordings'),
            auto_save=data.get('auto_save', True),
            compression_quality=data.get('compression_quality', 85),
            click_detection_sensitivity=data.get('click_detection_sensitivity', 0.5),
            record_mic=data.get('record_mic', False),
            mic_device_id=data.get('mic_device_id', None)
        )


@dataclass
class RecordingSession:
    """Represents an active or completed recording session."""
    session_id: str
    start_time: float
    end_time: Optional[float] = None
    total_frames: int = 0
    duration: float = 0.0
    status: str = 'idle'  # 'idle', 'recording', 'processing', 'completed'
    settings: Optional[RecordingSettings] = None
    click_events: list = None
    
    def __post_init__(self):
        if self.click_events is None:
            self.click_events = []
        if self.settings is None:
            self.settings = RecordingSettings()
    
    def add_click_event(self, click_event: ClickEvent):
        """Add a click event to the session."""
        self.click_events.append(click_event)
    
    def get_duration(self) -> float:
        """Calculate session duration."""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time if self.status == 'recording' else 0.0