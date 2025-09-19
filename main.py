#!/usr/bin/env python3
"""
Pinpoint Capture - Intelligent Screen Recorder with Zoom Effects

Main entry point for the application.
This script initializes and launches the Pinpoint Capture application.

Author: Pinpoint Capture Team
Version: 1.0.0
"""

import sys
import os
import logging
from pathlib import Path

# Add src directory to Python path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
except ImportError as e:
    print(f"Error importing PyQt6: {e}")
    print("Please install PyQt6: pip install PyQt6")
    sys.exit(1)

try:
    from src.app_controller import ApplicationController
    from src.config_manager import ConfigManager
except ImportError as e:
    print(f"Error importing application modules: {e}")
    print("Please ensure all required modules are in the src directory.")
    sys.exit(1)


def setup_logging():
    """Set up logging configuration."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / "pinpoint_capture.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific log levels for different modules
    logging.getLogger("PyQt6").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    

def check_dependencies():
    """Check if all required dependencies are available."""
    required_modules = [
        ('cv2', 'opencv-python'),
        ('mss', 'mss'),
        ('pynput', 'pynput'),
        ('numpy', 'numpy'),
        ('PIL', 'Pillow')
    ]
    
    missing_modules = []
    
    for module_name, package_name in required_modules:
        try:
            __import__(module_name)
        except ImportError:
            missing_modules.append(package_name)
    
    if missing_modules:
        error_msg = (
            "Missing required dependencies:\n\n"
            + "\n".join(f"- {pkg}" for pkg in missing_modules)
            + "\n\nPlease install them using:\n"
            + f"pip install {' '.join(missing_modules)}"
        )
        
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "Missing Dependencies", error_msg)
        return False
    
    return True


def check_system_requirements():
    """Check system requirements."""
    # Check Python version
    if sys.version_info < (3, 8):
        error_msg = (
            f"Python 3.8 or higher is required.\n"
            f"Current version: {sys.version_info.major}.{sys.version_info.minor}"
        )
        
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "System Requirements", error_msg)
        return False
    
    # Check if running on supported platform
    if sys.platform not in ['win32', 'darwin', 'linux']:
        error_msg = f"Unsupported platform: {sys.platform}"
        
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "System Requirements", error_msg)
        return False
    
    return True


def create_directories():
    """Create necessary directories if they don't exist."""
    directories = [
        Path("recordings"),
        Path("config"),
        Path("logs"),
        Path("temp")
    ]
    
    for directory in directories:
        try:
            directory.mkdir(exist_ok=True)
            logging.info(f"Directory created/verified: {directory}")
        except Exception as e:
            logging.error(f"Failed to create directory {directory}: {e}")
            return False
    
    return True


def setup_application():
    """Set up the QApplication with proper settings."""
    # Enable high DPI scaling for PyQt6
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        # Fallback for older PyQt6 versions
        pass
    
    app = QApplication(sys.argv)
    app.setApplicationName("Pinpoint Capture")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("Pinpoint Capture Team")
    
    # Set application icon if available
    icon_path = Path("assets") / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    
    return app


def main():
    """Main application entry point."""
    print("Starting Pinpoint Capture...")
    
    # Check system requirements
    if not check_system_requirements():
        return 1
    
    # Set up logging
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Pinpoint Capture starting up")
    
    # Check dependencies
    if not check_dependencies():
        logger.error("Dependency check failed")
        return 1
    
    # Create necessary directories
    if not create_directories():
        logger.error("Failed to create necessary directories")
        return 1
    
    # Set up QApplication
    app = setup_application()
    
    try:
        # Initialize application controller
        app_controller = ApplicationController()
        logger.info("Application controller initialized")
        
        # Initialize the application
        if not app_controller.initialize():
            logger.error("Application initialization failed")
            return 1
        
        # Start the application
        result = app_controller.run()
        logger.info(f"Application finished with result: {result}")
        
        return result
        
    except Exception as e:
        logger.exception(f"Unhandled exception in main: {e}")
        
        # Show error dialog
        try:
            QMessageBox.critical(
                None,
                "Application Error",
                f"An unexpected error occurred:\n\n{str(e)}\n\n"
                f"Please check the log file for more details."
            )
        except:
            print(f"Critical error: {e}")
        
        return 1
    
    finally:
        # Cleanup
        try:
            if 'app_controller' in locals():
                app_controller.shutdown()
        except Exception as e:
            logger.exception(f"Error during cleanup: {e}")


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nApplication interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)