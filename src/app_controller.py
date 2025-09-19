"""Application controller for Pinpoint Capture."""

import sys
import logging
import signal
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon

from .main_window import MainWindow
from .config_manager import ConfigManager
from .models import RecordingSettings


class ApplicationController(QObject):
    """Main application controller that manages the entire application lifecycle."""
    
    # Signals
    shutdown_requested = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.logger = self._setup_logging()
        
        # Application components
        self.app: Optional[QApplication] = None
        self.main_window: Optional[MainWindow] = None
        self.config_manager: Optional[ConfigManager] = None
        
        # Application state
        self.is_initialized = False
        self.is_shutting_down = False
        
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
        
        self.logger.info("Application controller initialized")
    
    def _setup_logging(self) -> logging.Logger:
        """Set up application logging."""
        # Create logs directory
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / 'pinpoint_capture.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        logger = logging.getLogger(__name__)
        logger.info("Logging system initialized")
        return logger
    
    def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            self.logger.debug("Signal handlers configured")
        except Exception as e:
            self.logger.warning(f"Could not set up signal handlers: {e}")
    
    def _signal_handler(self, signum, frame):
        """Handle system signals for graceful shutdown."""
        self.logger.info(f"Received signal {signum}, initiating shutdown")
        self.shutdown_requested.emit()
    
    def initialize(self) -> bool:
        """Initialize the application."""
        try:
            self.logger.info("Initializing Pinpoint Capture application")
            
            # Create QApplication
            self.app = QApplication(sys.argv)
            self.app.setApplicationName("Pinpoint Capture")
            self.app.setApplicationVersion("1.0.0")
            self.app.setOrganizationName("Pinpoint Capture")
            
            # Set application icon if available
            self._set_application_icon()
            
            # Initialize configuration manager
            self.config_manager = ConfigManager()
            
            # Verify system requirements
            if not self._check_system_requirements():
                return False
            
            # Create and setup main window
            self.main_window = MainWindow()
            
            # Connect shutdown signal
            self.shutdown_requested.connect(self._handle_shutdown_request)
            
            # Setup application-level event handling
            self.app.aboutToQuit.connect(self._on_application_quit)
            
            self.is_initialized = True
            self.logger.info("Application initialization completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize application: {e}")
            self._show_error_dialog("Initialization Error", f"Failed to initialize application:\n\n{e}")
            return False
    
    def _set_application_icon(self):
        """Set application icon if available."""
        try:
            icon_path = Path("assets") / "icon.png"
            if icon_path.exists():
                self.app.setWindowIcon(QIcon(str(icon_path)))
                self.logger.debug("Application icon set")
        except Exception as e:
            self.logger.debug(f"Could not set application icon: {e}")
    
    def _check_system_requirements(self) -> bool:
        """Check if system meets requirements."""
        try:
            # Check Python version
            if sys.version_info < (3, 8):
                self._show_error_dialog(
                    "System Requirements",
                    "Python 3.8 or higher is required."
                )
                return False
            
            # Check if required directories exist and are writable
            required_dirs = ['recordings', 'config', 'logs']
            for dir_name in required_dirs:
                dir_path = Path(dir_name)
                try:
                    dir_path.mkdir(exist_ok=True)
                    # Test write access
                    test_file = dir_path / '.write_test'
                    test_file.write_text('test')
                    test_file.unlink()
                except Exception as e:
                    self._show_error_dialog(
                        "System Requirements",
                        f"Cannot write to {dir_name} directory: {e}"
                    )
                    return False
            
            self.logger.info("System requirements check passed")
            return True
            
        except Exception as e:
            self.logger.error(f"System requirements check failed: {e}")
            return False
    
    def run(self) -> int:
        """Run the application."""
        if not self.is_initialized:
            self.logger.error("Application not initialized")
            return 1
        
        try:
            self.logger.info("Starting Pinpoint Capture application")
            
            # Show main window
            self.main_window.show()
            
            # Center window on screen
            self._center_window()
            
            # Start application event loop
            exit_code = self.app.exec()
            
            self.logger.info(f"Application exited with code: {exit_code}")
            return exit_code
            
        except Exception as e:
            self.logger.error(f"Error running application: {e}")
            return 1
    
    def _center_window(self):
        """Center the main window on screen."""
        try:
            if self.main_window:
                screen = self.app.primaryScreen()
                screen_geometry = screen.availableGeometry()
                window_geometry = self.main_window.geometry()
                
                x = (screen_geometry.width() - window_geometry.width()) // 2
                y = (screen_geometry.height() - window_geometry.height()) // 2
                
                self.main_window.move(x, y)
                self.logger.debug("Main window centered on screen")
        except Exception as e:
            self.logger.debug(f"Could not center window: {e}")
    
    def _handle_shutdown_request(self):
        """Handle shutdown request."""
        if self.is_shutting_down:
            return
        
        self.logger.info("Shutdown requested")
        self.shutdown()
    
    def shutdown(self):
        """Shutdown the application gracefully."""
        if self.is_shutting_down:
            return
        
        self.is_shutting_down = True
        self.logger.info("Initiating application shutdown")
        
        try:
            # Close main window if it exists
            if self.main_window:
                self.main_window.close()
            
            # Quit application
            if self.app:
                QTimer.singleShot(100, self.app.quit)
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
    
    def _on_application_quit(self):
        """Handle application quit event."""
        self.logger.info("Application quit event received")
        
        try:
            # Cleanup resources
            if self.main_window:
                # Save any pending settings
                if hasattr(self.main_window, 'save_settings_from_ui'):
                    self.main_window.save_settings_from_ui()
                
                # Cleanup recording components
                if hasattr(self.main_window, 'recording_controller'):
                    self.main_window.recording_controller.cleanup_components()
            
            self.logger.info("Application cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during application cleanup: {e}")
    
    def _show_error_dialog(self, title: str, message: str):
        """Show error dialog to user."""
        try:
            if self.app:
                QMessageBox.critical(None, title, message)
            else:
                print(f"ERROR - {title}: {message}")
        except Exception as e:
            print(f"ERROR - {title}: {message}")
            print(f"Additional error showing dialog: {e}")
    
    def get_application_info(self) -> dict:
        """Get application information."""
        return {
            'name': 'Pinpoint Capture',
            'version': '1.0.0',
            'description': 'Screen recorder with intelligent zoom functionality',
            'initialized': self.is_initialized,
            'shutting_down': self.is_shutting_down,
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'qt_version': self.app.applicationVersion() if self.app else 'Unknown'
        }
    
    def restart_application(self):
        """Restart the application."""
        self.logger.info("Restarting application")
        
        try:
            # Save current state
            if self.main_window and hasattr(self.main_window, 'save_settings_from_ui'):
                self.main_window.save_settings_from_ui()
            
            # Schedule restart
            QTimer.singleShot(1000, lambda: self._perform_restart())
            
            # Shutdown current instance
            self.shutdown()
            
        except Exception as e:
            self.logger.error(f"Error restarting application: {e}")
    
    def _perform_restart(self):
        """Perform the actual restart."""
        try:
            import subprocess
            subprocess.Popen([sys.executable] + sys.argv)
            self.logger.info("New application instance started")
        except Exception as e:
            self.logger.error(f"Failed to restart application: {e}")


def create_application() -> ApplicationController:
    """Factory function to create application controller."""
    return ApplicationController()


def main() -> int:
    """Main entry point for the application."""
    controller = create_application()
    
    if not controller.initialize():
        return 1
    
    return controller.run()


if __name__ == '__main__':
    sys.exit(main())