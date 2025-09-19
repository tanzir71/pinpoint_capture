"""Video processing engine for Pinpoint Capture application."""

import cv2
import numpy as np
import threading
import time
import logging
from typing import Optional, List, Tuple, Callable
from queue import Queue, Empty
from pathlib import Path
import uuid

from .models import ClickEvent, RecordingSettings, RecordingSession


class VideoProcessor:
    """Handles video processing, zoom effects, and output generation."""
    
    def __init__(self, settings: RecordingSettings):
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        
        # Video writer
        self.video_writer: Optional[cv2.VideoWriter] = None
        self.output_path: Optional[Path] = None
        
        # Processing state
        self.is_processing = False
        self.processing_thread: Optional[threading.Thread] = None
        self.frame_queue = Queue(maxsize=200)
        
        # Zoom state
        self.current_zoom_level = 1.0
        self.target_zoom_level = 1.0
        self.zoom_center = (0, 0)
        self.zoom_start_time = 0
        self.zoom_duration = 0
        self.is_zooming = False
        
        # Click events for zoom triggers
        self.pending_clicks: List[ClickEvent] = []
        self.active_zoom_click: Optional[ClickEvent] = None
        
        # Frame processing
        self.frames_processed = 0
        self.start_time = 0
        
        # Callbacks
        self.progress_callback: Optional[Callable[[float], None]] = None
        
        self.logger.info("Video processor initialized")
    
    def set_progress_callback(self, callback: Callable[[float], None]):
        """Set callback for processing progress updates."""
        self.progress_callback = callback
    
    def start_processing(self, output_filename: str) -> bool:
        """Start video processing and recording."""
        if self.is_processing:
            self.logger.warning("Video processing already active")
            return False
        
        try:
            # Setup output path
            output_dir = Path(self.settings.output_path)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            if not output_filename.endswith(f'.{self.settings.output_format}'):
                output_filename += f'.{self.settings.output_format}'
            
            self.output_path = output_dir / output_filename
            
            # Initialize video writer
            fourcc = self._get_fourcc()
            frame_size = self.settings.resolution
            
            self.video_writer = cv2.VideoWriter(
                str(self.output_path),
                fourcc,
                self.settings.fps,
                frame_size
            )
            
            if not self.video_writer.isOpened():
                raise Exception("Failed to initialize video writer")
            
            # Reset state
            self.is_processing = True
            self.frames_processed = 0
            self.start_time = time.time()
            self.current_zoom_level = 1.0
            self.target_zoom_level = 1.0
            self.is_zooming = False
            self.pending_clicks.clear()
            
            # Clear frame queue
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except Empty:
                    break
            
            # Start processing thread
            self.processing_thread = threading.Thread(
                target=self._processing_loop,
                daemon=True,
                name="VideoProcessingThread"
            )
            self.processing_thread.start()
            
            self.logger.info(f"Video processing started, output: {self.output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error starting video processing: {e}")
            self._cleanup_writer()
            return False
    
    def stop_processing(self) -> bool:
        """Stop video processing and finalize output."""
        if not self.is_processing:
            return True
        
        try:
            self.is_processing = False
            
            # Wait for processing thread to finish
            if self.processing_thread and self.processing_thread.is_alive():
                self.processing_thread.join(timeout=5.0)
            
            # Finalize video
            self._cleanup_writer()
            
            duration = time.time() - self.start_time
            avg_fps = self.frames_processed / duration if duration > 0 else 0
            
            self.logger.info(f"Video processing stopped. Processed {self.frames_processed} frames in {duration:.2f}s (avg {avg_fps:.1f} FPS)")
            return True
            
        except Exception as e:
            self.logger.error(f"Error stopping video processing: {e}")
            return False
    
    def add_frame(self, frame: np.ndarray, timestamp: float) -> bool:
        """Add a frame to the processing queue."""
        if not self.is_processing:
            return False
        
        try:
            if not self.frame_queue.full():
                self.frame_queue.put((frame, timestamp), block=False)
                return True
            else:
                # Remove oldest frame if queue is full
                try:
                    self.frame_queue.get_nowait()
                    self.frame_queue.put((frame, timestamp), block=False)
                    return True
                except Empty:
                    return False
        except Exception as e:
            self.logger.error(f"Error adding frame: {e}")
            return False
    
    def add_click_event(self, click_event: ClickEvent):
        """Add a click event to trigger zoom effect."""
        if self.is_processing:
            self.pending_clicks.append(click_event)
            self.logger.debug(f"Click event added for zoom: ({click_event.x}, {click_event.y})")
    
    def _processing_loop(self):
        """Main video processing loop."""
        try:
            while self.is_processing:
                try:
                    # Get next frame
                    frame_data = self.frame_queue.get(timeout=0.1)
                    if frame_data is None:
                        continue
                    
                    frame, timestamp = frame_data
                    
                    # Process zoom effects
                    processed_frame = self._process_frame_with_zoom(frame, timestamp)
                    
                    # Resize frame to target resolution if needed
                    if processed_frame.shape[:2][::-1] != self.settings.resolution:
                        processed_frame = cv2.resize(processed_frame, self.settings.resolution)
                    
                    # Write frame to video
                    if self.video_writer and self.video_writer.isOpened():
                        # Convert RGB to BGR for OpenCV
                        bgr_frame = cv2.cvtColor(processed_frame, cv2.COLOR_RGB2BGR)
                        self.video_writer.write(bgr_frame)
                        self.frames_processed += 1
                    
                    # Update progress
                    if self.progress_callback and self.frames_processed % 30 == 0:
                        try:
                            progress = min(1.0, self.frames_processed / (self.settings.fps * 60))  # Estimate based on 1 minute
                            self.progress_callback(progress)
                        except Exception as e:
                            self.logger.error(f"Error in progress callback: {e}")
                    
                except Empty:
                    continue
                except Exception as e:
                    self.logger.error(f"Error in processing loop: {e}")
                    time.sleep(0.01)
                    
        except Exception as e:
            self.logger.error(f"Fatal error in processing loop: {e}")
        finally:
            self.logger.debug("Processing loop ended")
    
    def _process_frame_with_zoom(self, frame: np.ndarray, timestamp: float) -> np.ndarray:
        """Process frame with zoom effects based on click events."""
        # Check for new click events to trigger zoom
        self._check_for_zoom_triggers(timestamp)
        
        # Update zoom state
        self._update_zoom_state(timestamp)
        
        # Apply zoom if active
        if self.current_zoom_level > 1.0:
            return self._apply_zoom_effect(frame)
        
        return frame
    
    def _check_for_zoom_triggers(self, timestamp: float):
        """Check if any pending clicks should trigger a zoom effect."""
        if not self.pending_clicks or self.is_zooming:
            return
        
        # Find the most recent click within trigger window
        trigger_window = 0.5  # 500ms window to trigger zoom
        recent_clicks = [click for click in self.pending_clicks 
                        if timestamp - click.timestamp <= trigger_window]
        
        if recent_clicks:
            # Use the most recent click
            latest_click = max(recent_clicks, key=lambda c: c.timestamp)
            self._start_zoom_effect(latest_click, timestamp)
            
            # Remove processed clicks
            self.pending_clicks = [click for click in self.pending_clicks 
                                 if click.timestamp > latest_click.timestamp]
    
    def _start_zoom_effect(self, click_event: ClickEvent, current_time: float):
        """Start zoom effect centered on click location."""
        self.active_zoom_click = click_event
        self.zoom_center = (click_event.x, click_event.y)
        self.target_zoom_level = self.settings.zoom_level
        self.zoom_start_time = current_time
        self.zoom_duration = self.settings.zoom_duration
        self.is_zooming = True
        
        self.logger.debug(f"Zoom effect started at ({click_event.x}, {click_event.y}), level: {self.target_zoom_level}")
    
    def _update_zoom_state(self, timestamp: float):
        """Update current zoom level based on time and settings."""
        if not self.is_zooming:
            return
        
        elapsed = timestamp - self.zoom_start_time
        transition_speed = self.settings.transition_speed
        
        if elapsed < self.zoom_duration:
            # Zoom in phase
            progress = min(1.0, elapsed * transition_speed)
            self.current_zoom_level = 1.0 + (self.target_zoom_level - 1.0) * self._ease_in_out(progress)
        elif elapsed < self.zoom_duration * 2:
            # Zoom out phase
            progress = min(1.0, (elapsed - self.zoom_duration) * transition_speed)
            self.current_zoom_level = self.target_zoom_level - (self.target_zoom_level - 1.0) * self._ease_in_out(progress)
        else:
            # Zoom complete
            self.current_zoom_level = 1.0
            self.is_zooming = False
            self.active_zoom_click = None
    
    def _ease_in_out(self, t: float) -> float:
        """Smooth easing function for zoom transitions."""
        return t * t * (3.0 - 2.0 * t)
    
    def _apply_zoom_effect(self, frame: np.ndarray) -> np.ndarray:
        """Apply zoom effect to frame."""
        try:
            height, width = frame.shape[:2]
            
            # Calculate zoom region
            zoom_width = int(width / self.current_zoom_level)
            zoom_height = int(height / self.current_zoom_level)
            
            # Center zoom on click location, but keep within bounds
            center_x = max(zoom_width // 2, min(width - zoom_width // 2, self.zoom_center[0]))
            center_y = max(zoom_height // 2, min(height - zoom_height // 2, self.zoom_center[1]))
            
            # Extract zoom region
            x1 = center_x - zoom_width // 2
            y1 = center_y - zoom_height // 2
            x2 = x1 + zoom_width
            y2 = y1 + zoom_height
            
            # Ensure bounds
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, x2), min(height, y2)
            
            # Extract and resize zoom region
            zoom_region = frame[y1:y2, x1:x2]
            zoomed_frame = cv2.resize(zoom_region, (width, height), interpolation=cv2.INTER_LANCZOS4)
            
            return zoomed_frame
            
        except Exception as e:
            self.logger.error(f"Error applying zoom effect: {e}")
            return frame
    
    def _get_fourcc(self) -> int:
        """Get appropriate FourCC codec for output format."""
        format_codecs = {
            'mp4': cv2.VideoWriter_fourcc(*'mp4v'),
            'avi': cv2.VideoWriter_fourcc(*'XVID'),
            'mov': cv2.VideoWriter_fourcc(*'mp4v')
        }
        return format_codecs.get(self.settings.output_format, cv2.VideoWriter_fourcc(*'mp4v'))
    
    def _cleanup_writer(self):
        """Clean up video writer resources."""
        try:
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None
        except Exception as e:
            self.logger.error(f"Error cleaning up video writer: {e}")
    
    def get_processing_stats(self) -> dict:
        """Get video processing statistics."""
        if self.start_time == 0:
            return {'status': 'not_started'}
        
        current_time = time.time()
        duration = current_time - self.start_time
        avg_fps = self.frames_processed / duration if duration > 0 else 0
        
        return {
            'status': 'processing' if self.is_processing else 'stopped',
            'frames_processed': self.frames_processed,
            'duration': duration,
            'average_fps': avg_fps,
            'target_fps': self.settings.fps,
            'queue_size': self.frame_queue.qsize(),
            'current_zoom_level': self.current_zoom_level,
            'is_zooming': self.is_zooming,
            'pending_clicks': len(self.pending_clicks),
            'output_path': str(self.output_path) if self.output_path else None
        }
    
    def update_settings(self, settings: RecordingSettings):
        """Update video processor settings."""
        self.settings = settings
        self.logger.debug("Video processor settings updated")
    
    def cleanup(self):
        """Clean up resources."""
        try:
            self.stop_processing()
            self._cleanup_writer()
            self.logger.info("Video processor cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")