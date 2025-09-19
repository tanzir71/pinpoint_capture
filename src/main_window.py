"""Main window GUI for Pinpoint Capture application."""

import sys
import os
import time
from pathlib import Path
from typing import Optional
import logging
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame, QGroupBox, QSlider, QSpinBox,
    QComboBox, QLineEdit, QTextEdit, QProgressBar, QFileDialog,
    QMessageBox, QStatusBar, QSplitter, QTabWidget, QCheckBox
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QThread, pyqtSlot, QSize
)
from PyQt6.QtGui import (
    QPixmap, QFont, QIcon, QPalette, QColor, QAction
)

from .models import RecordingSettings, RecordingSession
from .config_manager import ConfigManager
from .screen_capture import ScreenCapture
from .mouse_handler import MouseEventHandler
from .video_processor import VideoProcessor


class RecordingController(QThread):
    """Thread controller for recording operations."""
    
    # Signals
    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal(str)  # output file path
    recording_error = pyqtSignal(str)  # error message
    frame_captured = pyqtSignal(int)  # frame count
    click_detected = pyqtSignal(int, int)  # x, y coordinates
    
    def __init__(self, settings: RecordingSettings):
        super().__init__()
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        
        # Components
        self.screen_capture: Optional[ScreenCapture] = None
        self.mouse_handler: Optional[MouseEventHandler] = None
        self.video_processor: Optional[VideoProcessor] = None
        
        # State
        self.is_recording = False
        self.session: Optional[RecordingSession] = None
        self.frame_count = 0
        # NEW: track monitor offset for coordinate transform
        self.monitor_offset = (0, 0)
        
    def setup_components(self):
        """Initialize recording components."""
        try:
            # Initialize screen capture
            self.screen_capture = ScreenCapture(self.settings)
            self.screen_capture.set_frame_callback(self._on_frame_captured)
            
            # Initialize mouse handler
            self.mouse_handler = MouseEventHandler(self.settings)
            self.mouse_handler.set_click_callback(self._on_click_detected)
            
            # Initialize video processor
            self.video_processor = VideoProcessor(self.settings)
            
            self.logger.info("Recording components initialized")
            return True
            
        except Exception as e:
            self.logger.error(f"Error setting up components: {e}")
            self.recording_error.emit(f"Failed to initialize recording components: {e}")
            return False
    
    def start_recording(self, output_filename: str):
        """Start recording session."""
        if self.is_recording:
            return
        
        try:
            if not self.setup_components():
                return
            
            # Create recording session
            self.session = RecordingSession(
                session_id=f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                start_time=time.time(),
                settings=self.settings
            )
            
            # Start components
            if not self.video_processor.start_processing(output_filename):
                raise Exception("Failed to start video processor")
            
            if not self.screen_capture.start_capture():
                raise Exception("Failed to start screen capture")

            # NEW: after capture starts, set mouse handler resolution and monitor offset
            if self.screen_capture and self.mouse_handler and hasattr(self.screen_capture, 'target_monitor'):
                mon = self.screen_capture.target_monitor
                self.monitor_offset = (mon['left'], mon['top'])
                self.mouse_handler.set_screen_resolution((mon['width'], mon['height']))
            
            self.mouse_handler.start_monitoring()
            
            self.is_recording = True
            self.frame_count = 0
            self.recording_started.emit()
            
            self.logger.info(f"Recording started: {output_filename}")
            
        except Exception as e:
            self.logger.error(f"Error starting recording: {e}")
            self.recording_error.emit(f"Failed to start recording: {e}")
            self.cleanup_components()
    
    def stop_recording(self):
        """Stop recording session."""
        if not self.is_recording:
            return
        
        try:
            self.is_recording = False
            
            # Stop components
            if self.mouse_handler:
                self.mouse_handler.stop_monitoring()
            
            if self.screen_capture:
                self.screen_capture.stop_capture()
            
            if self.video_processor:
                self.video_processor.stop_processing()
            
            # Finalize session
            output_path = ""
            if self.session and self.video_processor:
                stats = self.video_processor.get_processing_stats()
                output_path = stats.get('output_path', '')
                # End the recording session
                self.session.end_time = time.time()
                self.session.status = 'completed'
                self.session.duration = self.session.get_duration()
            
            self.cleanup_components()
            self.recording_stopped.emit(output_path)
            
            self.logger.info("Recording stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping recording: {e}")
            self.recording_error.emit(f"Failed to stop recording: {e}")
    
    def cleanup_components(self):
        """Clean up recording components."""
        try:
            if self.video_processor:
                self.video_processor.cleanup()
                self.video_processor = None
            
            if self.screen_capture:
                self.screen_capture.cleanup()
                self.screen_capture = None
            
            if self.mouse_handler:
                self.mouse_handler.cleanup()
                self.mouse_handler = None
                
        except Exception as e:
            self.logger.error(f"Error cleaning up components: {e}")
    
    def _on_frame_captured(self, frame, timestamp):
        """Handle captured frame."""
        if self.is_recording and self.video_processor:
            self.video_processor.add_frame(frame, timestamp)
            self.frame_count += 1
            
            if self.frame_count % 30 == 0:  # Emit every 30 frames
                self.frame_captured.emit(self.frame_count)
    
    def _on_click_detected(self, click_event):
        """Handle detected click."""
        if self.is_recording and self.video_processor:
            # NEW: convert global screen coords to frame-relative coords
            processed_click = click_event
            try:
                if self.screen_capture and hasattr(self.screen_capture, 'target_monitor'):
                    mon = self.screen_capture.target_monitor
                    mon_left, mon_top = mon['left'], mon['top']
                    mon_w, mon_h = mon['width'], mon['height']
                    adj_x = max(0, min(mon_w - 1, click_event.x - mon_left))
                    adj_y = max(0, min(mon_h - 1, click_event.y - mon_top))
                    processed_click = ClickEvent.create_now(adj_x, adj_y, click_event.button, (mon_w, mon_h))
                    # Emit adjusted coords for UI
                    self.click_detected.emit(int(adj_x), int(adj_y))
                else:
                    self.click_detected.emit(int(click_event.x), int(click_event.y))
            except Exception:
                self.click_detected.emit(int(click_event.x), int(click_event.y))

            self.video_processor.add_click_event(processed_click)
            self.click_detected.emit(click_event.x, click_event.y)
    
    def update_settings(self, settings: RecordingSettings):
        """Update recording settings."""
        self.settings = settings
        if self.video_processor:
            self.video_processor.update_settings(settings)
        if self.mouse_handler:
            self.mouse_handler.update_settings(settings)


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        # Configuration
        self.config_manager = ConfigManager()
        self.settings = self.config_manager.load_settings()
        
        # Recording controller
        self.recording_controller = RecordingController(self.settings)
        self.setup_recording_signals()
        
        # UI state
        self.is_recording = False
        self.recording_start_time = None
        self.frame_count = 0
        
        # Timers
        self.recording_timer = QTimer()
        self.recording_timer.timeout.connect(self.update_recording_time)
        
        self.setup_ui()
        self.setup_styles()
        self.load_settings_to_ui()
        
        self.logger.info("Main window initialized")
    
    def setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Pinpoint Capture - Screen Recorder with Smart Zoom")
        self.setMinimumSize(800, 600)
        self.resize(1000, 700)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout(central_widget)
        
        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left panel - Controls
        self.setup_control_panel(splitter)
        
        # Right panel - Preview and logs
        self.setup_preview_panel(splitter)
        
        # Status bar
        self.setup_status_bar()
        
        # Set splitter proportions
        splitter.setSizes([400, 600])
    
    def setup_control_panel(self, parent):
        """Set up the control panel."""
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        
        # Recording controls
        self.setup_recording_controls(control_layout)
        
        # Settings panel
        self.setup_settings_panel(control_layout)
        
        # Output settings
        self.setup_output_settings(control_layout)
        
        control_layout.addStretch()
        parent.addWidget(control_widget)
    
    def setup_recording_controls(self, layout):
        """Set up recording control buttons."""
        group = QGroupBox("Recording Controls")
        group_layout = QVBoxLayout(group)
        
        # Main recording button
        self.record_button = QPushButton("Start Recording")
        self.record_button.setMinimumHeight(50)
        self.record_button.clicked.connect(self.toggle_recording)
        group_layout.addWidget(self.record_button)
        
        # Recording info
        info_layout = QGridLayout()
        
        info_layout.addWidget(QLabel("Status:"), 0, 0)
        self.status_label = QLabel("Ready")
        info_layout.addWidget(self.status_label, 0, 1)
        
        info_layout.addWidget(QLabel("Duration:"), 1, 0)
        self.duration_label = QLabel("00:00:00")
        info_layout.addWidget(self.duration_label, 1, 1)
        
        info_layout.addWidget(QLabel("Frames:"), 2, 0)
        self.frames_label = QLabel("0")
        info_layout.addWidget(self.frames_label, 2, 1)
        
        group_layout.addLayout(info_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        group_layout.addWidget(self.progress_bar)
        
        layout.addWidget(group)
    
    def setup_settings_panel(self, layout):
        """Set up settings panel."""
        group = QGroupBox("Zoom Settings")
        group_layout = QGridLayout(group)
        
        # Zoom level
        group_layout.addWidget(QLabel("Zoom Level:"), 0, 0)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(150, 500)  # 1.5x to 5.0x
        self.zoom_slider.setValue(int(self.settings.zoom_level * 100))
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        group_layout.addWidget(self.zoom_slider, 0, 1)
        
        self.zoom_label = QLabel(f"{self.settings.zoom_level:.1f}x")
        group_layout.addWidget(self.zoom_label, 0, 2)
        
        # Zoom duration
        group_layout.addWidget(QLabel("Zoom Duration:"), 1, 0)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(500, 5000)
        self.duration_spin.setValue(int(self.settings.zoom_duration * 1000))
        self.duration_spin.setSuffix(" ms")
        self.duration_spin.valueChanged.connect(self.on_duration_changed)
        group_layout.addWidget(self.duration_spin, 1, 1, 1, 2)
        
        # Transition speed
        group_layout.addWidget(QLabel("Transition Speed:"), 2, 0)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(1, 10)
        self.speed_slider.setValue(int(self.settings.transition_speed))
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        group_layout.addWidget(self.speed_slider, 2, 1)
        
        self.speed_label = QLabel(f"{self.settings.transition_speed:.1f}")
        group_layout.addWidget(self.speed_label, 2, 2)
        
        layout.addWidget(group)
    
    def setup_output_settings(self, layout):
        """Set up output settings panel."""
        group = QGroupBox("Output Settings")
        group_layout = QGridLayout(group)
        
        # Output format
        group_layout.addWidget(QLabel("Format:"), 0, 0)
        self.format_combo = QComboBox()
        self.format_combo.addItems(['mp4', 'avi', 'mov'])
        self.format_combo.setCurrentText(self.settings.output_format)
        self.format_combo.currentTextChanged.connect(self.on_format_changed)
        group_layout.addWidget(self.format_combo, 0, 1)
        
        # FPS
        group_layout.addWidget(QLabel("FPS:"), 1, 0)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(10, 60)
        self.fps_spin.setValue(self.settings.fps)
        self.fps_spin.valueChanged.connect(self.on_fps_changed)
        group_layout.addWidget(self.fps_spin, 1, 1)
        
        # Output directory
        group_layout.addWidget(QLabel("Output Dir:"), 2, 0)
        self.output_path_edit = QLineEdit(self.settings.output_path)
        self.output_path_edit.textChanged.connect(self.on_output_path_changed)
        group_layout.addWidget(self.output_path_edit, 2, 1)
        
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.browse_output_directory)
        group_layout.addWidget(browse_button, 2, 2)
        
        layout.addWidget(group)
    
    def setup_preview_panel(self, parent):
        """Set up preview and logs panel."""
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        
        # Tab widget for preview and logs
        tab_widget = QTabWidget()
        
        # Preview tab
        preview_tab = QWidget()
        preview_tab_layout = QVBoxLayout(preview_tab)
        
        self.preview_label = QLabel("Preview will appear here when recording starts")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(300)
        self.preview_label.setStyleSheet("border: 2px dashed #ccc; background-color: #f9f9f9;")
        preview_tab_layout.addWidget(self.preview_label)
        
        tab_widget.addTab(preview_tab, "Preview")
        
        # Logs tab
        logs_tab = QWidget()
        logs_tab_layout = QVBoxLayout(logs_tab)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        # Note: QTextEdit doesn't have setMaximumBlockCount in PyQt6
        # We'll manage log size manually if needed
        logs_tab_layout.addWidget(self.log_text)
        
        tab_widget.addTab(logs_tab, "Logs")
        
        preview_layout.addWidget(tab_widget)
        parent.addWidget(preview_widget)
    
    def setup_status_bar(self):
        """Set up status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.status_bar.showMessage("Ready to record")
    
    def setup_styles(self):
        """Set up application styles."""
        # Set modern color scheme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            QSlider::groove:horizontal {
                border: 1px solid #bbb;
                background: white;
                height: 10px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #4CAF50;
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
        """)
    
    def setup_recording_signals(self):
        """Connect recording controller signals."""
        self.recording_controller.recording_started.connect(self.on_recording_started)
        self.recording_controller.recording_stopped.connect(self.on_recording_stopped)
        self.recording_controller.recording_error.connect(self.on_recording_error)
        self.recording_controller.frame_captured.connect(self.on_frame_captured)
        self.recording_controller.click_detected.connect(self.on_click_detected)
    
    def load_settings_to_ui(self):
        """Load settings into UI controls."""
        self.zoom_slider.setValue(int(self.settings.zoom_level * 100))
        self.duration_spin.setValue(int(self.settings.zoom_duration * 1000))
        self.speed_slider.setValue(int(self.settings.transition_speed))
        self.format_combo.setCurrentText(self.settings.output_format)
        self.fps_spin.setValue(self.settings.fps)
        self.output_path_edit.setText(self.settings.output_path)
        
        self.update_zoom_label()
        self.update_speed_label()
    
    def toggle_recording(self):
        """Toggle recording state."""
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()
    
    def start_recording(self):
        """Start recording."""
        # Generate output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"pinpoint_capture_{timestamp}"
        
        # Update settings from UI
        self.save_settings_from_ui()
        self.recording_controller.update_settings(self.settings)
        
        # Start recording
        self.recording_controller.start_recording(filename)
    
    def stop_recording(self):
        """Stop recording."""
        self.recording_controller.stop_recording()
    
    def save_settings_from_ui(self):
        """Save current UI settings."""
        self.settings.zoom_level = self.zoom_slider.value() / 100.0
        self.settings.zoom_duration = self.duration_spin.value() / 1000.0
        self.settings.transition_speed = self.speed_slider.value()
        self.settings.output_format = self.format_combo.currentText()
        self.settings.fps = self.fps_spin.value()
        self.settings.output_path = self.output_path_edit.text()
        
        self.config_manager.save_settings(self.settings)
    
    # UI Event Handlers
    def on_zoom_changed(self, value):
        """Handle zoom level change."""
        self.settings.zoom_level = value / 100.0
        self.update_zoom_label()
    
    def on_duration_changed(self, value):
        """Handle zoom duration change."""
        self.settings.zoom_duration = value / 1000.0
    
    def on_speed_changed(self, value):
        """Handle transition speed change."""
        self.settings.transition_speed = value
        self.update_speed_label()
    
    def on_format_changed(self, format_name):
        """Handle output format change."""
        self.settings.output_format = format_name
    
    def on_fps_changed(self, fps):
        """Handle FPS change."""
        self.settings.fps = fps
    
    def on_output_path_changed(self, path):
        """Handle output path change."""
        self.settings.output_path = path
    
    def browse_output_directory(self):
        """Browse for output directory."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", self.settings.output_path
        )
        if directory:
            self.output_path_edit.setText(directory)
            self.settings.output_path = directory
    
    def update_zoom_label(self):
        """Update zoom level label."""
        self.zoom_label.setText(f"{self.settings.zoom_level:.1f}x")
    
    def update_speed_label(self):
        """Update speed label."""
        self.speed_label.setText(f"{self.settings.transition_speed:.1f}")
    
    # Recording Event Handlers
    @pyqtSlot()
    def on_recording_started(self):
        """Handle recording started."""
        self.is_recording = True
        self.recording_start_time = datetime.now()
        self.frame_count = 0
        
        self.record_button.setText("Stop Recording")
        self.record_button.setStyleSheet("background-color: #f44336;")
        self.status_label.setText("Recording")
        self.progress_bar.setVisible(True)
        
        self.recording_timer.start(1000)  # Update every second
        self.status_bar.showMessage("Recording in progress...")
        
        self.log_message("Recording started")
    
    @pyqtSlot(str)
    def on_recording_stopped(self, output_path):
        """Handle recording stopped."""
        self.is_recording = False
        self.recording_timer.stop()
        
        self.record_button.setText("Start Recording")
        self.record_button.setStyleSheet("background-color: #4CAF50;")
        self.status_label.setText("Ready")
        self.progress_bar.setVisible(False)
        self.duration_label.setText("00:00:00")
        
        if output_path:
            self.status_bar.showMessage(f"Recording saved: {output_path}")
            self.log_message(f"Recording saved to: {output_path}")
            
            # Show completion message
            QMessageBox.information(
                self, "Recording Complete", 
                f"Recording saved successfully!\n\nFile: {output_path}\nFrames: {self.frame_count}"
            )
        else:
            self.status_bar.showMessage("Recording stopped")
            self.log_message("Recording stopped")
    
    @pyqtSlot(str)
    def on_recording_error(self, error_message):
        """Handle recording error."""
        self.is_recording = False
        self.recording_timer.stop()
        
        self.record_button.setText("Start Recording")
        self.record_button.setStyleSheet("background-color: #4CAF50;")
        self.status_label.setText("Error")
        self.progress_bar.setVisible(False)
        
        self.status_bar.showMessage(f"Error: {error_message}")
        self.log_message(f"ERROR: {error_message}")
        
        QMessageBox.critical(self, "Recording Error", f"An error occurred:\n\n{error_message}")
    
    @pyqtSlot(int)
    def on_frame_captured(self, frame_count):
        """Handle frame captured update."""
        self.frame_count = frame_count
        self.frames_label.setText(str(frame_count))
    
    @pyqtSlot(int, int)
    def on_click_detected(self, x, y):
        """Handle click detected."""
        self.log_message(f"Click detected at ({x}, {y}) - Zoom triggered")
    
    def update_recording_time(self):
        """Update recording duration display."""
        if self.recording_start_time:
            duration = datetime.now() - self.recording_start_time
            total_seconds = int(duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            self.duration_label.setText(time_str)
    
    def log_message(self, message):
        """Add message to log display."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.log_text.append(formatted_message)
        
        # Auto-scroll to bottom
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)
    
    def closeEvent(self, event):
        """Handle window close event."""
        if self.is_recording:
            reply = QMessageBox.question(
                self, "Recording in Progress",
                "Recording is still in progress. Stop recording and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_recording()
                # Wait a moment for cleanup
                QTimer.singleShot(1000, lambda: event.accept())
                event.ignore()
            else:
                event.ignore()
        else:
            # Save settings before closing
            self.save_settings_from_ui()
            self.recording_controller.cleanup_components()
            event.accept()