"""Main window GUI for Pinpoint Capture application."""

import sys
import os
import time
import subprocess
from pathlib import Path
from typing import Optional
import logging
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame, QGroupBox, QSlider, QSpinBox,
    QComboBox, QLineEdit, QTextEdit, QProgressBar, QFileDialog,
    QMessageBox, QStatusBar, QSplitter, QTabWidget, QCheckBox, QSizePolicy, QLayout
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QThread, pyqtSlot, QSize
)
from PyQt6.QtGui import (
    QPixmap, QFont, QIcon, QPalette, QColor, QAction
)

from .models import RecordingSettings, RecordingSession, ClickEvent
from .config_manager import ConfigManager
from .screen_capture import ScreenCapture
from .mouse_handler import MouseEventHandler
from .video_processor import VideoProcessor
from .audio_recorder import AudioRecorder
from string import Template


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
        self.audio_recorder: Optional[AudioRecorder] = None
        
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
            
            # Initialize audio recorder if microphone recording is enabled
            if self.settings.record_mic:
                self.audio_recorder = AudioRecorder()
                if self.settings.mic_device_id is not None:
                    self.audio_recorder.set_device(self.settings.mic_device_id)
                self.logger.info("Audio recorder initialized")
            
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
            
            # Start audio recording if enabled
            if self.settings.record_mic and self.audio_recorder:
                if not self.audio_recorder.start_recording():
                    self.logger.warning("Failed to start audio recording, continuing without audio")
                else:
                    self.logger.info("Audio recording started")
            
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
            
            # Stop audio recording and save audio file if enabled
            audio_file_path = None
            if self.settings.record_mic and self.audio_recorder:
                self.audio_recorder.stop_recording()
                
                # Save temporary audio file
                if self.session:
                    base_path = Path(self.session.session_id)
                    audio_file_path = str(base_path.with_suffix('.wav'))
                    
                    if self.audio_recorder.save_audio(audio_file_path):
                        self.logger.info(f"Audio saved: {audio_file_path}")
                    else:
                        self.logger.warning("Failed to save audio file")
                        audio_file_path = None
            
            if self.video_processor:
                self.video_processor.stop_processing()
            
            # Finalize session
            output_path = ""
            if self.session and self.video_processor:
                stats = self.video_processor.get_processing_stats()
                video_path = stats.get('output_path', '')
                
                # Combine audio and video if both exist
                if audio_file_path and video_path and Path(audio_file_path).exists() and Path(video_path).exists():
                    output_path = self._combine_audio_video(video_path, audio_file_path)
                    if output_path:
                        self.logger.info(f"Audio and video combined: {output_path}")
                        # Clean up temporary files
                        try:
                            Path(audio_file_path).unlink()
                            Path(video_path).unlink()
                            self.logger.info("Temporary files cleaned up")
                        except Exception as e:
                            self.logger.warning(f"Failed to clean up temporary files: {e}")
                    else:
                        output_path = video_path
                        self.logger.warning("Failed to combine audio and video, keeping video only")
                else:
                    output_path = video_path
                    
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
            
            if self.audio_recorder:
                self.audio_recorder.cleanup()
                self.audio_recorder = None
                
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
            # Convert global screen coords to frame-relative coords when possible
            processed_click = click_event
            try:
                if self.screen_capture and hasattr(self.screen_capture, 'target_monitor'):
                    mon = self.screen_capture.target_monitor
                    mon_left, mon_top = mon['left'], mon['top']
                    mon_w, mon_h = mon['width'], mon['height']
                    adj_x = max(0, min(mon_w - 1, click_event.x - mon_left))
                    adj_y = max(0, min(mon_h - 1, click_event.y - mon_top))
                    processed_click = ClickEvent.create_now(int(adj_x), int(adj_y), click_event.button, (mon_w, mon_h))
                    # Emit adjusted coords for UI
                    self.click_detected.emit(int(adj_x), int(adj_y))
                else:
                    # Fallback: emit as-is if monitor not known
                    self.click_detected.emit(int(click_event.x), int(click_event.y))
            except Exception:
                self.click_detected.emit(int(click_event.x), int(click_event.y))

            # Only add the processed (adjusted) click to the processor
            self.video_processor.add_click_event(processed_click)
    
    def update_settings(self, settings: RecordingSettings):
        """Update recording settings."""
        self.settings = settings
        if self.video_processor:
            self.video_processor.update_settings(settings)
    
    def _combine_audio_video(self, video_path: str, audio_path: str) -> Optional[str]:
        """Combine audio and video files using FFmpeg."""
        try:
            video_file = Path(video_path)
            audio_file = Path(audio_path)
            
            # Create output filename with combined suffix
            output_file = video_file.with_name(f"{video_file.stem}_with_audio{video_file.suffix}")
            
            # FFmpeg command to combine audio and video
            cmd = [
                'ffmpeg',
                '-i', str(video_file),  # Video input
                '-i', str(audio_file),  # Audio input
                '-c:v', 'copy',         # Copy video codec (no re-encoding)
                '-c:a', 'aac',          # Encode audio to AAC
                '-strict', 'experimental',
                '-y',                   # Overwrite output file
                str(output_file)
            ]
            
            # Run FFmpeg command
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                self.logger.info(f"Successfully combined audio and video: {output_file}")
                return str(output_file)
            else:
                self.logger.error(f"FFmpeg failed: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            self.logger.error("FFmpeg command timed out")
            return None
        except FileNotFoundError:
            self.logger.error("FFmpeg not found. Please install FFmpeg to combine audio and video.")
            return None
        except Exception as e:
             self.logger.error(f"Error combining audio and video: {e}")
             return None


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
        self.setWindowTitle("Pinpoint Capture")
        # Compact window size for narrower interface
        self.setMinimumSize(480, 620)
        self.resize(520, 680)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout (compact, single column)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        # Prevent child cropping by honoring minimum sizes
        main_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        
        # Controls only (no preview/logs)
        self.setup_control_panel(main_layout)
        
        # Status bar
        self.setup_status_bar()
        
    
    def setup_control_panel(self, parent_layout):
        """Set up the control panel in a compact form."""
        control_widget = QWidget()
        control_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        control_layout = QVBoxLayout(control_widget)
        # Honor minimum sizes inside this panel
        control_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        
        # Recording controls
        self.setup_recording_controls(control_layout)
        
        # Settings panel
        self.setup_settings_panel(control_layout)
        
        # Output settings
        self.setup_output_settings(control_layout)
        
        control_layout.addStretch()
        parent_layout.addWidget(control_widget, 1)
        
    def setup_recording_controls(self, layout):
        """Set up recording control buttons."""
        group = QGroupBox("Recording Controls")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(10, 10, 10, 10)
        group_layout.setSpacing(10)
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        group_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        
        # Main recording button
        self.record_button = QPushButton("Start Recording")
        self.record_button.setMinimumHeight(56)
        self.record_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.record_button.clicked.connect(self.toggle_recording)
        group_layout.addWidget(self.record_button)
        
        # Visual separator to ensure clear spacing below the button
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        group_layout.addWidget(separator)
        
        # Recording info
        info_layout = QGridLayout()
        info_layout.setVerticalSpacing(6)
        info_layout.setColumnStretch(1, 1)
        
        status_text_label = QLabel("Status:")
        status_text_label.setMinimumHeight(24)
        status_text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(status_text_label, 0, 0)
        self.status_label = QLabel("Ready")
        self.status_label.setMinimumHeight(24)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(self.status_label, 0, 1)
        
        duration_text_label = QLabel("Duration:")
        duration_text_label.setMinimumHeight(24)
        duration_text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(duration_text_label, 1, 0)
        self.duration_label = QLabel("00:00:00")
        self.duration_label.setMinimumHeight(24)
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(self.duration_label, 1, 1)
        
        frames_text_label = QLabel("Frames:")
        frames_text_label.setMinimumHeight(24)
        frames_text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(frames_text_label, 2, 0)
        self.frames_label = QLabel("0")
        self.frames_label.setMinimumHeight(24)
        self.frames_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(self.frames_label, 2, 1)
        
        group_layout.addLayout(info_layout)
        
        # Progress bar - reserve space to prevent layout shifts
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimumHeight(16)
        self.progress_bar.setMaximumHeight(16)
        # Always add the progress bar but keep it hidden to reserve space
        group_layout.addWidget(self.progress_bar)
        
        # Audio controls section
        audio_separator = QFrame()
        audio_separator.setFrameShape(QFrame.Shape.HLine)
        audio_separator.setFrameShadow(QFrame.Shadow.Sunken)
        group_layout.addWidget(audio_separator)
        
        audio_layout = QGridLayout()
        audio_layout.setVerticalSpacing(6)
        audio_layout.setColumnStretch(1, 1)
        
        # Record microphone checkbox
        self.record_mic_checkbox = QCheckBox("Record Microphone")
        self.record_mic_checkbox.setChecked(self.settings.record_mic)
        self.record_mic_checkbox.stateChanged.connect(self.on_record_mic_changed)
        audio_layout.addWidget(self.record_mic_checkbox, 0, 0, 1, 2)
        
        # Microphone device selection
        mic_device_label = QLabel("Microphone:")
        mic_device_label.setMinimumHeight(24)
        mic_device_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        audio_layout.addWidget(mic_device_label, 1, 0)
        
        self.mic_device_combo = QComboBox()
        self.mic_device_combo.setMinimumHeight(24)
        self.mic_device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.populate_audio_devices()
        self.mic_device_combo.currentIndexChanged.connect(self.on_mic_device_changed)
        # Make the device combo behave better in narrow layouts
        self.mic_device_combo.setMinimumContentsLength(12)
        self.mic_device_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        audio_layout.addWidget(self.mic_device_combo, 1, 1)
        
        group_layout.addLayout(audio_layout)
        
        layout.addWidget(group)
    
    def setup_settings_panel(self, layout):
        """Set up settings panel."""
        group = QGroupBox("Zoom Settings")
        group_layout = QGridLayout(group)
        group_layout.setContentsMargins(10, 10, 10, 10)
        group_layout.setHorizontalSpacing(8)
        group_layout.setVerticalSpacing(8)
        group_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        
        # Zoom level
        zoom_label = QLabel("Zoom Level:")
        zoom_label.setMinimumHeight(24)
        zoom_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        group_layout.addWidget(zoom_label, 0, 0)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(150, 500)  # 1.5x to 5.0x
        self.zoom_slider.setValue(int(self.settings.zoom_level * 100))
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        self.zoom_slider.setMinimumHeight(22)
        self.zoom_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        group_layout.addWidget(self.zoom_slider, 0, 1)
        
        self.zoom_label = QLabel(f"{self.settings.zoom_level:.1f}x")
        self.zoom_label.setMinimumHeight(24)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        group_layout.addWidget(self.zoom_label, 0, 2)
        # Zoom duration
        group_layout.addWidget(QLabel("Zoom Duration:"), 1, 0)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(500, 5000)
        self.duration_spin.setValue(int(self.settings.zoom_duration * 1000))
        self.duration_spin.setSuffix(" ms")
        self.duration_spin.valueChanged.connect(self.on_duration_changed)
        # Set arrow button symbols
        self.duration_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self.duration_spin.setMaximumWidth(100)
        group_layout.addWidget(self.duration_spin, 1, 1, 1, 2)
        
        # Transition speed
        group_layout.addWidget(QLabel("Transition Speed:"), 2, 0)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(1, 10)
        self.speed_slider.setValue(int(self.settings.transition_speed))
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        self.speed_slider.setMinimumHeight(22)
        group_layout.addWidget(self.speed_slider, 2, 1)
        
        self.speed_label = QLabel(f"{self.settings.transition_speed:.1f}")
        group_layout.addWidget(self.speed_label, 2, 2)
        
        layout.addWidget(group)
    
    def setup_output_settings(self, layout):
        """Set up output settings panel."""
        group = QGroupBox("Output Settings")
        group_layout = QGridLayout(group)
        group_layout.setContentsMargins(10, 10, 10, 10)
        group_layout.setHorizontalSpacing(8)
        group_layout.setVerticalSpacing(8)
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        # Ensure the line edit expands and the browse button remains visible
        group_layout.setColumnStretch(1, 1)
        group_layout.setColumnMinimumWidth(2, 76)
        group_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        
        # Output format
        format_label = QLabel("Format:")
        format_label.setMinimumHeight(24)
        format_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        group_layout.addWidget(format_label, 0, 0)
        self.format_combo = QComboBox()
        self.format_combo.addItems(['mp4', 'avi', 'mov'])
        self.format_combo.setCurrentText(self.settings.output_format)
        self.format_combo.currentTextChanged.connect(self.on_format_changed)
        self.format_combo.setMinimumHeight(28)
        self.format_combo.setMaximumWidth(100)
        self.format_combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        group_layout.addWidget(self.format_combo, 0, 1)
        
        # FPS
        fps_label = QLabel("FPS:")
        fps_label.setMinimumHeight(24)
        fps_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        group_layout.addWidget(fps_label, 1, 0)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(10, 60)
        self.fps_spin.setValue(self.settings.fps)
        self.fps_spin.valueChanged.connect(self.on_fps_changed)
        self.fps_spin.setMinimumHeight(28)
        self.fps_spin.setMaximumWidth(80)
        self.fps_spin.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        # Set arrow button symbols
        self.fps_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        group_layout.addWidget(self.fps_spin, 1, 1)
        
        # Output directory
        output_label = QLabel("Output Dir:")
        output_label.setMinimumHeight(24)
        output_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        group_layout.addWidget(output_label, 2, 0)
        self.output_path_edit = QLineEdit(self.settings.output_path)
        self.output_path_edit.textChanged.connect(self.on_output_path_changed)
        self.output_path_edit.setMinimumHeight(28)
        self.output_path_edit.setMinimumWidth(160)
        self.output_path_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        group_layout.addWidget(self.output_path_edit, 2, 1)
        
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.browse_output_directory)
        browse_button.setMinimumHeight(32)
        browse_button.setMinimumWidth(70)
        browse_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
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
        # Build absolute icon paths for spinbox arrows (use forward slashes for Qt)
        project_root = Path(__file__).resolve().parents[1]
        up_icon_path = (project_root / 'icons' / 'chevron-up.svg').as_posix()
        down_icon_path = (project_root / 'icons' / 'chevron-down.svg').as_posix()
    
        style_template = Template("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QWidget {
                color: #222222;
            }
            QLabel {
                color: #222222;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #dddddd;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 8px;
                color: #222222;
                background-color: #ffffff;
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
            QLineEdit, QComboBox, QSpinBox {
                background-color: #ffffff;
                color: #222222;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 2px 6px;
            }
            /* Ensure QComboBox dropdown list is readable */
            QComboBox {
                padding-right: 24px; /* space for arrow */
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #222222;
                border: 1px solid #cccccc;
                selection-background-color: #4CAF50;
                selection-color: #ffffff;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #cccccc;
                background: #f8f8f8;
            }
            QComboBox::drop-down:hover {
                background: #e8e8e8;
            }
            QComboBox::down-arrow {
                image: url('$down_icon_path');
                width: 12px;
                height: 12px;
            }
            QComboBox::down-arrow:disabled {
                image: url('$down_icon_path');
            }
            /* Ensure QMessageBox details and buttons are readable */
            QMessageBox QTextEdit {
                background-color: #ffffff;
                color: #222222;
                border: 1px solid #cccccc;
            }
            QMessageBox QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QMessageBox QPushButton:hover {
                background-color: #45a049;
            }
            QMessageBox QPushButton:pressed {
                background-color: #3d8b40;
            }
            QMessageBox QToolButton {
                background-color: #f8f8f8;
                color: #222222;
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 2px 6px;
            }
            QMessageBox QToolButton:hover {
                background-color: #e8e8e8;
            }
            QMessageBox {
                background-color: #ffffff;
                color: #222222;
            }
            QMessageBox QLabel {
                color: #222222;
            }
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 4px;
                background-color: #f0f0f0;
                text-align: center;
                color: #222222;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
            QSlider::groove:horizontal {
                border: 1px solid #bbb;
                background: #ffffff;
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
            QSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 20px;
                border-left-width: 1px;
                border-left-color: #cccccc;
                border-left-style: solid;
                border-top-right-radius: 3px;
                background: #f8f8f8;
            }
            QSpinBox::up-button:hover {
                background: #e8e8e8;
            }
            QSpinBox::up-button:pressed {
                background: #d8d8d8;
            }
            /* Explicit arrow icons to ensure visibility when using QSS */
            QSpinBox::up-arrow {
                image: url('$up_icon_path');
                width: 12px;
                height: 12px;
            }
            QSpinBox::up-arrow:disabled {
                image: url('$up_icon_path');
            }
            QSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 20px;
                border-left-width: 1px;
                border-left-color: #cccccc;
                border-left-style: solid;
                border-bottom-right-radius: 3px;
                background: #f8f8f8;
            }
            QSpinBox::down-button:hover {
                background: #e8e8e8;
            }
            QSpinBox::down-button:pressed {
                background: #d8d8d8;
            }
            QSpinBox::down-arrow {
                image: url('$down_icon_path');
                width: 12px;
                height: 12px;
            }
            QSpinBox::down-arrow:disabled {
                image: url('$down_icon_path');
            }
        """)

        self.setStyleSheet(style_template.substitute(
            up_icon_path=up_icon_path,
            down_icon_path=down_icon_path,
        ))
    
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
        self.config_manager.save_settings(self.settings)
    
    def on_duration_changed(self, value):
        """Handle zoom duration change."""
        self.settings.zoom_duration = value / 1000.0
        self.config_manager.save_settings(self.settings)
    
    def on_speed_changed(self, value):
        """Handle transition speed change."""
        self.settings.transition_speed = value
        self.update_speed_label()
        self.config_manager.save_settings(self.settings)
    
    def on_format_changed(self, format_name):
        """Handle output format change."""
        self.settings.output_format = format_name
        self.config_manager.save_settings(self.settings)
    
    def on_fps_changed(self, fps):
        """Handle FPS change."""
        self.settings.fps = fps
        self.config_manager.save_settings(self.settings)
    
    def on_output_path_changed(self, path):
        """Handle output path change."""
        self.settings.output_path = path
        self.config_manager.save_settings(self.settings)
    
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
        # Keep progress bar visible to prevent layout shifts
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        
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
        # Hide progress bar after recording stops
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)  # Reset to normal range
        self.duration_label.setText("00:00:00")
        
        if output_path:
            self.status_bar.showMessage(f"Recording saved: {output_path}")
            self.log_message(f"Recording saved to: {output_path}")
            
            # Show completion message with proper styling
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Recording Complete")
            msg_box.setText("Recording saved successfully!")
            msg_box.setDetailedText(f"File: {output_path}\nFrames: {self.frame_count}")
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.exec()
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
        # Hide progress bar after error
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)  # Reset to normal range
        
        self.status_bar.showMessage(f"Error: {error_message}")
        self.log_message(f"ERROR: {error_message}")
        
        # Show error message with proper styling
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Recording Error")
        msg_box.setText("An error occurred during recording:")
        msg_box.setDetailedText(error_message)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.exec()
    
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
    
    def populate_audio_devices(self):
        """Populate the microphone device dropdown."""
        self.mic_device_combo.clear()
        
        try:
            devices = AudioRecorder.get_audio_devices()
            
            if not devices:
                self.mic_device_combo.addItem("No audio devices found", None)
                self.mic_device_combo.setEnabled(False)
                return
            
            # Add default device option
            default_id = AudioRecorder.get_default_device_id()
            self.mic_device_combo.addItem("Default Device", default_id)
            
            # Add all available devices
            for device in devices:
                device_name = f"{device['name']} ({device['channels']} ch)"
                self.mic_device_combo.addItem(device_name, device['id'])
            
            # Set current selection based on settings
            if self.settings.mic_device_id is not None:
                for i in range(self.mic_device_combo.count()):
                    if self.mic_device_combo.itemData(i) == self.settings.mic_device_id:
                        self.mic_device_combo.setCurrentIndex(i)
                        break
            
            self.mic_device_combo.setEnabled(True)
            
        except Exception as e:
            self.log_message(f"Error loading audio devices: {e}")
            self.mic_device_combo.addItem("Error loading devices", None)
            self.mic_device_combo.setEnabled(False)
    
    def on_record_mic_changed(self, state):
        """Handle record microphone checkbox change."""
        self.settings.record_mic = state == Qt.CheckState.Checked.value
        self.config_manager.save_settings(self.settings)
        self.log_message(f"Microphone recording {'enabled' if self.settings.record_mic else 'disabled'}")
    
    def on_mic_device_changed(self, index):
        """Handle microphone device selection change."""
        device_id = self.mic_device_combo.itemData(index)
        self.settings.mic_device_id = device_id
        self.config_manager.save_settings(self.settings)
        
        device_name = self.mic_device_combo.currentText()
        self.log_message(f"Microphone device changed to: {device_name}")
    
    def log_message(self, message):
        """Display message in status bar (logs panel removed)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        if hasattr(self, "status_bar") and self.status_bar is not None:
            self.status_bar.showMessage(formatted_message)
        # Also log to application logger
        self.logger.info(message)
    
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