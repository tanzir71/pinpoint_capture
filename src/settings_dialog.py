from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit, QPushButton,
    QCheckBox, QSlider, QLabel, QFileDialog, QTabWidget, QWidget,
    QMessageBox, QColorDialog
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
import os
from pathlib import Path
from models import RecordingSettings
from config_manager import ConfigManager


class SettingsDialog(QDialog):
    """Settings dialog for configuring recording parameters."""
    
    settings_changed = pyqtSignal(RecordingSettings)
    
    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.current_settings = config_manager.get_settings()
        
        self.setWindowTitle("Pinpoint Capture Settings")
        self.setModal(True)
        self.resize(500, 600)
        
        self.setup_ui()
        self.load_current_settings()
        
    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create tabs
        self.create_recording_tab()
        self.create_zoom_tab()
        self.create_output_tab()
        self.create_advanced_tab()
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.reset_button = QPushButton("Reset to Defaults")
        self.reset_button.clicked.connect(self.reset_to_defaults)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply_settings)
        
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept_settings)
        self.ok_button.setDefault(True)
        
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.ok_button)
        
        layout.addLayout(button_layout)
        
    def create_recording_tab(self):
        """Create the recording settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Recording Quality Group
        quality_group = QGroupBox("Recording Quality")
        quality_layout = QFormLayout(quality_group)
        
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(10, 120)
        self.fps_spinbox.setSuffix(" fps")
        quality_layout.addRow("Frame Rate:", self.fps_spinbox)
        
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["Low", "Medium", "High", "Ultra"])
        quality_layout.addRow("Video Quality:", self.quality_combo)
        
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["mp4v", "XVID", "H264"])
        quality_layout.addRow("Video Codec:", self.codec_combo)
        
        layout.addWidget(quality_group)
        
        # Recording Behavior Group
        behavior_group = QGroupBox("Recording Behavior")
        behavior_layout = QFormLayout(behavior_group)
        
        self.auto_stop_checkbox = QCheckBox()
        behavior_layout.addRow("Auto-stop after inactivity:", self.auto_stop_checkbox)
        
        self.inactivity_spinbox = QSpinBox()
        self.inactivity_spinbox.setRange(5, 300)
        self.inactivity_spinbox.setSuffix(" seconds")
        behavior_layout.addRow("Inactivity timeout:", self.inactivity_spinbox)
        
        self.show_cursor_checkbox = QCheckBox()
        behavior_layout.addRow("Show cursor in recording:", self.show_cursor_checkbox)
        
        layout.addWidget(behavior_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Recording")
        
    def create_zoom_tab(self):
        """Create the zoom settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Zoom Parameters Group
        zoom_group = QGroupBox("Zoom Parameters")
        zoom_layout = QFormLayout(zoom_group)
        
        self.zoom_factor_spinbox = QDoubleSpinBox()
        self.zoom_factor_spinbox.setRange(1.1, 5.0)
        self.zoom_factor_spinbox.setSingleStep(0.1)
        self.zoom_factor_spinbox.setDecimals(1)
        self.zoom_factor_spinbox.setSuffix("x")
        zoom_layout.addRow("Zoom Factor:", self.zoom_factor_spinbox)
        
        self.zoom_duration_spinbox = QSpinBox()
        self.zoom_duration_spinbox.setRange(500, 5000)
        self.zoom_duration_spinbox.setSuffix(" ms")
        zoom_layout.addRow("Zoom Duration:", self.zoom_duration_spinbox)
        
        self.zoom_area_spinbox = QSpinBox()
        self.zoom_area_spinbox.setRange(50, 500)
        self.zoom_area_spinbox.setSuffix(" px")
        zoom_layout.addRow("Zoom Area Size:", self.zoom_area_spinbox)
        
        layout.addWidget(zoom_group)
        
        # Zoom Effects Group
        effects_group = QGroupBox("Zoom Effects")
        effects_layout = QFormLayout(effects_group)
        
        self.smooth_zoom_checkbox = QCheckBox()
        effects_layout.addRow("Smooth zoom transition:", self.smooth_zoom_checkbox)
        
        self.highlight_click_checkbox = QCheckBox()
        effects_layout.addRow("Highlight click area:", self.highlight_click_checkbox)
        
        # Highlight color selection
        self.highlight_color_button = QPushButton()
        self.highlight_color_button.setFixedSize(50, 30)
        self.highlight_color_button.clicked.connect(self.choose_highlight_color)
        effects_layout.addRow("Highlight Color:", self.highlight_color_button)
        
        layout.addWidget(effects_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Zoom")
        
    def create_output_tab(self):
        """Create the output settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Output Directory Group
        output_group = QGroupBox("Output Settings")
        output_layout = QFormLayout(output_group)
        
        # Output directory selection
        dir_layout = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setReadOnly(True)
        
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse_output_directory)
        
        dir_layout.addWidget(self.output_dir_edit)
        dir_layout.addWidget(self.browse_button)
        output_layout.addRow("Output Directory:", dir_layout)
        
        # Filename pattern
        self.filename_pattern_edit = QLineEdit()
        self.filename_pattern_edit.setPlaceholderText("e.g., recording_{timestamp}")
        output_layout.addRow("Filename Pattern:", self.filename_pattern_edit)
        
        # File format
        self.format_combo = QComboBox()
        self.format_combo.addItems([".mp4", ".avi", ".mov"])
        output_layout.addRow("File Format:", self.format_combo)
        
        layout.addWidget(output_group)
        
        # Auto-cleanup Group
        cleanup_group = QGroupBox("Auto-cleanup")
        cleanup_layout = QFormLayout(cleanup_group)
        
        self.auto_cleanup_checkbox = QCheckBox()
        cleanup_layout.addRow("Enable auto-cleanup:", self.auto_cleanup_checkbox)
        
        self.max_files_spinbox = QSpinBox()
        self.max_files_spinbox.setRange(1, 1000)
        cleanup_layout.addRow("Max files to keep:", self.max_files_spinbox)
        
        self.max_size_spinbox = QSpinBox()
        self.max_size_spinbox.setRange(100, 10000)
        self.max_size_spinbox.setSuffix(" MB")
        cleanup_layout.addRow("Max total size:", self.max_size_spinbox)
        
        layout.addWidget(cleanup_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Output")
        
    def create_advanced_tab(self):
        """Create the advanced settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Performance Group
        performance_group = QGroupBox("Performance")
        performance_layout = QFormLayout(performance_group)
        
        self.buffer_size_spinbox = QSpinBox()
        self.buffer_size_spinbox.setRange(10, 1000)
        self.buffer_size_spinbox.setSuffix(" frames")
        performance_layout.addRow("Buffer Size:", self.buffer_size_spinbox)
        
        self.thread_count_spinbox = QSpinBox()
        self.thread_count_spinbox.setRange(1, 8)
        performance_layout.addRow("Processing Threads:", self.thread_count_spinbox)
        
        self.compression_slider = QSlider(Qt.Orientation.Horizontal)
        self.compression_slider.setRange(0, 9)
        self.compression_label = QLabel("5")
        compression_layout = QHBoxLayout()
        compression_layout.addWidget(self.compression_slider)
        compression_layout.addWidget(self.compression_label)
        self.compression_slider.valueChanged.connect(
            lambda v: self.compression_label.setText(str(v))
        )
        performance_layout.addRow("Compression Level:", compression_layout)
        
        layout.addWidget(performance_group)
        
        # Debug Group
        debug_group = QGroupBox("Debug")
        debug_layout = QFormLayout(debug_group)
        
        self.debug_mode_checkbox = QCheckBox()
        debug_layout.addRow("Enable debug mode:", self.debug_mode_checkbox)
        
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        debug_layout.addRow("Log Level:", self.log_level_combo)
        
        layout.addWidget(debug_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Advanced")
        
    def load_current_settings(self):
        """Load current settings into the dialog."""
        settings = self.current_settings
        
        # Recording tab
        self.fps_spinbox.setValue(settings.fps)
        quality_map = {60: 0, 70: 1, 80: 2, 90: 3}  # Low, Medium, High, Ultra
        self.quality_combo.setCurrentIndex(quality_map.get(settings.quality, 2))
        
        # Zoom tab
        self.zoom_factor_spinbox.setValue(settings.zoom_factor)
        self.zoom_duration_spinbox.setValue(settings.zoom_duration)
        self.zoom_area_spinbox.setValue(settings.zoom_area_size)
        self.smooth_zoom_checkbox.setChecked(settings.smooth_zoom)
        self.highlight_click_checkbox.setChecked(settings.highlight_clicks)
        
        # Set highlight color
        self.highlight_color = QColor(settings.highlight_color)
        self.update_color_button()
        
        # Output tab
        self.output_dir_edit.setText(settings.output_directory)
        self.filename_pattern_edit.setText(settings.filename_pattern)
        format_index = {".mp4": 0, ".avi": 1, ".mov": 2}.get(settings.output_format, 0)
        self.format_combo.setCurrentIndex(format_index)
        
        # Advanced tab
        self.buffer_size_spinbox.setValue(100)  # Default buffer size
        self.thread_count_spinbox.setValue(2)   # Default thread count
        self.compression_slider.setValue(5)     # Default compression
        
    def choose_highlight_color(self):
        """Open color dialog to choose highlight color."""
        color = QColorDialog.getColor(self.highlight_color, self)
        if color.isValid():
            self.highlight_color = color
            self.update_color_button()
            
    def update_color_button(self):
        """Update the color button appearance."""
        self.highlight_color_button.setStyleSheet(
            f"background-color: {self.highlight_color.name()};"
        )
        
    def browse_output_directory(self):
        """Browse for output directory."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", self.output_dir_edit.text()
        )
        if directory:
            self.output_dir_edit.setText(directory)
            
    def get_settings_from_dialog(self) -> RecordingSettings:
        """Create RecordingSettings object from dialog values."""
        # Map quality combo to quality value
        quality_values = [60, 70, 80, 90]  # Low, Medium, High, Ultra
        quality = quality_values[self.quality_combo.currentIndex()]
        
        # Map format combo to format string
        formats = [".mp4", ".avi", ".mov"]
        output_format = formats[self.format_combo.currentIndex()]
        
        return RecordingSettings(
            fps=self.fps_spinbox.value(),
            quality=quality,
            zoom_factor=self.zoom_factor_spinbox.value(),
            zoom_duration=self.zoom_duration_spinbox.value(),
            zoom_area_size=self.zoom_area_spinbox.value(),
            smooth_zoom=self.smooth_zoom_checkbox.isChecked(),
            highlight_clicks=self.highlight_click_checkbox.isChecked(),
            highlight_color=self.highlight_color.name(),
            output_directory=self.output_dir_edit.text(),
            filename_pattern=self.filename_pattern_edit.text(),
            output_format=output_format
        )
        
    def validate_settings(self) -> bool:
        """Validate the current settings."""
        # Check output directory exists
        output_dir = self.output_dir_edit.text()
        if not output_dir or not os.path.exists(output_dir):
            QMessageBox.warning(
                self, "Invalid Settings",
                "Please select a valid output directory."
            )
            return False
            
        # Check filename pattern
        pattern = self.filename_pattern_edit.text()
        if not pattern or '{timestamp}' not in pattern:
            QMessageBox.warning(
                self, "Invalid Settings",
                "Filename pattern must contain '{timestamp}' placeholder."
            )
            return False
            
        return True
        
    def apply_settings(self):
        """Apply the current settings."""
        if not self.validate_settings():
            return
            
        settings = self.get_settings_from_dialog()
        self.config_manager.save_settings(settings)
        self.current_settings = settings
        self.settings_changed.emit(settings)
        
    def accept_settings(self):
        """Accept and apply settings, then close dialog."""
        if not self.validate_settings():
            return
            
        self.apply_settings()
        self.accept()
        
    def reset_to_defaults(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self, "Reset Settings",
            "Are you sure you want to reset all settings to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.config_manager.reset_to_defaults()
            self.current_settings = self.config_manager.get_settings()
            self.load_current_settings()
            self.settings_changed.emit(self.current_settings)