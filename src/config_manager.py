"""Configuration manager for Pinpoint Capture application."""

import json
import os
from pathlib import Path
from typing import Optional
import logging

from .models import RecordingSettings


class ConfigManager:
    """Manages application configuration and settings persistence."""
    
    def __init__(self, config_dir: str = "./config"):
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "settings.json"
        self.logger = logging.getLogger(__name__)
        
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Default settings
        self._default_settings = RecordingSettings()
        
    def load_settings(self) -> RecordingSettings:
        """Load settings from configuration file."""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    settings = RecordingSettings.from_dict(data)
                    self.logger.info("Settings loaded successfully")
                    return settings
            else:
                self.logger.info("No config file found, using default settings")
                return self._default_settings
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.error(f"Error loading settings: {e}")
            self.logger.info("Using default settings")
            return self._default_settings
        except Exception as e:
            self.logger.error(f"Unexpected error loading settings: {e}")
            return self._default_settings
    
    def save_settings(self, settings: RecordingSettings) -> bool:
        """Save settings to configuration file."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(settings.to_dict(), f, indent=4)
            self.logger.info("Settings saved successfully")
            return True
        except Exception as e:
            self.logger.error(f"Error saving settings: {e}")
            return False
    
    def reset_to_defaults(self) -> RecordingSettings:
        """Reset settings to default values and save."""
        default_settings = RecordingSettings()
        self.save_settings(default_settings)
        self.logger.info("Settings reset to defaults")
        return default_settings
    
    def validate_settings(self, settings: RecordingSettings) -> bool:
        """Validate settings values are within acceptable ranges."""
        try:
            # Validate resolution
            if not (100 <= settings.resolution[0] <= 7680 and 100 <= settings.resolution[1] <= 4320):
                self.logger.warning("Invalid resolution values")
                return False
            
            # Validate FPS
            if not (1 <= settings.fps <= 120):
                self.logger.warning("Invalid FPS value")
                return False
            
            # Validate zoom level
            if not (1.0 <= settings.zoom_level <= 10.0):
                self.logger.warning("Invalid zoom level")
                return False
            
            # Validate zoom duration
            if not (0.5 <= settings.zoom_duration <= 30.0):
                self.logger.warning("Invalid zoom duration")
                return False
            
            # Validate transition speed
            if not (0.1 <= settings.transition_speed <= 5.0):
                self.logger.warning("Invalid transition speed")
                return False
            
            # Validate compression quality
            if not (1 <= settings.compression_quality <= 100):
                self.logger.warning("Invalid compression quality")
                return False
            
            # Validate click detection sensitivity
            if not (0.1 <= settings.click_detection_sensitivity <= 1.0):
                self.logger.warning("Invalid click detection sensitivity")
                return False
            
            # Validate output format
            if settings.output_format not in ['mp4', 'avi', 'mov']:
                self.logger.warning("Invalid output format")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating settings: {e}")
            return False
    
    def get_output_path(self, settings: RecordingSettings) -> Path:
        """Get the full output path for recordings."""
        output_path = Path(settings.output_path)
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        
        # Ensure output directory exists
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path
    
    def create_backup(self) -> bool:
        """Create a backup of current settings."""
        try:
            if self.config_file.exists():
                backup_file = self.config_dir / "settings_backup.json"
                import shutil
                shutil.copy2(self.config_file, backup_file)
                self.logger.info("Settings backup created")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error creating backup: {e}")
            return False
    
    def restore_backup(self) -> Optional[RecordingSettings]:
        """Restore settings from backup."""
        try:
            backup_file = self.config_dir / "settings_backup.json"
            if backup_file.exists():
                import shutil
                shutil.copy2(backup_file, self.config_file)
                self.logger.info("Settings restored from backup")
                return self.load_settings()
            return None
        except Exception as e:
            self.logger.error(f"Error restoring backup: {e}")
            return None