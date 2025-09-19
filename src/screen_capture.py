"""Screen capture module for Pinpoint Capture application."""

import mss
import numpy as np
from PIL import Image
import threading
import time
import logging
from typing import Optional, Callable, Tuple
from queue import Queue, Empty
import ctypes
import ctypes.wintypes
from ctypes import wintypes
import cv2

from .models import RecordingSettings


# Windows API structures for cursor capture
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("hCursor", wintypes.HANDLE),
                ("ptScreenPos", POINT)]

class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL),
                ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]

# Constants
CURSOR_SHOWING = 0x00000001


class ScreenCapture:
    """Handles screen capture operations using mss library."""
    
    def __init__(self, settings: RecordingSettings):
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self.sct = mss.mss()
        
        # Threading control
        self.is_capturing = False
        self.capture_thread: Optional[threading.Thread] = None
        self.frame_queue = Queue(maxsize=100)  # Buffer for frames
        
        # Callbacks
        self.frame_callback: Optional[Callable] = None
        
        # Performance metrics
        self.frames_captured = 0
        self.start_time = 0
        
        # Get monitor information
        self.monitors = self.sct.monitors
        self.primary_monitor = self.monitors[1]  # Index 0 is all monitors combined
        
        # Windows API for cursor capture
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        
        # Cursor capture settings
        self.capture_cursor = True  # Enable cursor capture by default
        
        self.logger.info(f"Screen capture initialized with {len(self.monitors)-1} monitors and cursor capture enabled")
    
    def get_monitor_info(self) -> dict:
        """Get information about available monitors."""
        monitor_info = {
            'primary': self.primary_monitor,
            'all_monitors': self.monitors[1:],  # Exclude the combined monitor
            'total_monitors': len(self.monitors) - 1
        }
        return monitor_info
    
    def set_cursor_capture(self, enabled: bool):
        """Enable or disable cursor capture."""
        self.capture_cursor = enabled
        self.logger.debug(f"Cursor capture {'enabled' if enabled else 'disabled'}")
    
    def _get_cursor_info(self) -> Optional[Tuple[int, int, int, int]]:
        """Get cursor position and size using Windows API."""
        try:
            cursor_info = CURSORINFO()
            cursor_info.cbSize = ctypes.sizeof(CURSORINFO)
            
            if not self.user32.GetCursorInfo(ctypes.byref(cursor_info)):
                return None
            
            if cursor_info.flags != CURSOR_SHOWING:
                return None
            
            # Get cursor position
            x, y = cursor_info.ptScreenPos.x, cursor_info.ptScreenPos.y
            
            # Get cursor icon info for hotspot
            icon_info = ICONINFO()
            if self.user32.GetIconInfo(cursor_info.hCursor, ctypes.byref(icon_info)):
                hotspot_x, hotspot_y = icon_info.xHotspot, icon_info.yHotspot
                # Clean up bitmap handles
                if icon_info.hbmMask:
                    self.gdi32.DeleteObject(icon_info.hbmMask)
                if icon_info.hbmColor:
                    self.gdi32.DeleteObject(icon_info.hbmColor)
            else:
                hotspot_x, hotspot_y = 0, 0
            
            return (x - hotspot_x, y - hotspot_y, 32, 32)  # Default cursor size 32x32
            
        except Exception as e:
            self.logger.debug(f"Error getting cursor info: {e}")
            return None
    
    def _draw_cursor_on_frame(self, frame: np.ndarray, monitor_offset: Tuple[int, int]) -> np.ndarray:
        """Draw cursor on the captured frame."""
        if not self.capture_cursor:
            return frame
        
        cursor_info = self._get_cursor_info()
        if not cursor_info:
            return frame
        
        cursor_x, cursor_y, cursor_w, cursor_h = cursor_info
        monitor_x, monitor_y = monitor_offset
        
        # Convert global cursor position to frame-relative position
        frame_x = cursor_x - monitor_x
        frame_y = cursor_y - monitor_y
        
        # Check if cursor is within frame bounds
        frame_height, frame_width = frame.shape[:2]
        if (frame_x < -cursor_w or frame_x > frame_width or 
            frame_y < -cursor_h or frame_y > frame_height):
            return frame
        
        # Draw a simple cursor representation (white arrow with black outline)
        try:
            # Ensure frame is in the correct format for OpenCV
            if frame.dtype != np.uint8:
                frame = frame.astype(np.uint8)
            
            # Make sure frame is contiguous in memory
            if not frame.flags['C_CONTIGUOUS']:
                frame = np.ascontiguousarray(frame)
            
            # Define cursor arrow points (relative to cursor position)
            arrow_points = np.array([
                [0, 0], [0, 16], [4, 12], [8, 20], [12, 16], [8, 12], [16, 12]
            ], np.int32)
            
            # Offset points to cursor position
            arrow_points[:, 0] += frame_x
            arrow_points[:, 1] += frame_y
            
            # Ensure all points are within frame bounds
            arrow_points[:, 0] = np.clip(arrow_points[:, 0], 0, frame.shape[1] - 1)
            arrow_points[:, 1] = np.clip(arrow_points[:, 1], 0, frame.shape[0] - 1)
            
            # Draw black outline
            cv2.fillPoly(frame, [arrow_points], (0, 0, 0))
            
            # Draw white fill (slightly smaller)
            arrow_fill = arrow_points.copy()
            arrow_fill[1:, :] = np.maximum(arrow_fill[1:, :] - 1, 0)  # Make fill slightly smaller
            cv2.fillPoly(frame, [arrow_fill], (255, 255, 255))
            
        except Exception as e:
            self.logger.debug(f"Error drawing cursor: {e}")
        
        return frame
    
    def set_frame_callback(self, callback: Callable[[np.ndarray, float], None]):
        """Set callback function to receive captured frames."""
        self.frame_callback = callback
    
    def start_capture(self, monitor_index: int = 1) -> bool:
        """Start screen capture in a separate thread."""
        if self.is_capturing:
            self.logger.warning("Capture already in progress")
            return False
        
        try:
            if monitor_index >= len(self.monitors):
                monitor_index = 1  # Default to primary monitor
            
            self.target_monitor = self.monitors[monitor_index]
            self.is_capturing = True
            self.frames_captured = 0
            self.start_time = time.time()
            
            # Clear frame queue
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except Empty:
                    break
            
            # Start capture thread
            self.capture_thread = threading.Thread(
                target=self._capture_loop,
                daemon=True,
                name="ScreenCaptureThread"
            )
            self.capture_thread.start()
            
            self.logger.info(f"Screen capture started on monitor {monitor_index}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error starting capture: {e}")
            self.is_capturing = False
            return False
    
    def stop_capture(self) -> bool:
        """Stop screen capture."""
        if not self.is_capturing:
            return True
        
        try:
            self.is_capturing = False
            
            # Wait for capture thread to finish
            if self.capture_thread and self.capture_thread.is_alive():
                self.capture_thread.join(timeout=2.0)
            
            duration = time.time() - self.start_time
            avg_fps = self.frames_captured / duration if duration > 0 else 0
            
            self.logger.info(f"Screen capture stopped. Captured {self.frames_captured} frames in {duration:.2f}s (avg {avg_fps:.1f} FPS)")
            return True
            
        except Exception as e:
            self.logger.error(f"Error stopping capture: {e}")
            return False
    
    def _capture_loop(self):
        """Main capture loop running in separate thread."""
        target_fps = self.settings.fps
        frame_interval = 1.0 / target_fps
        last_capture_time = 0
        
        # Create mss instance for this thread to avoid threading issues
        thread_sct = mss.mss()
        
        try:
            while self.is_capturing:
                current_time = time.time()
                
                # Control frame rate
                if current_time - last_capture_time < frame_interval:
                    time.sleep(0.001)  # Small sleep to prevent busy waiting
                    continue
                
                # Capture frame
                try:
                    screenshot = thread_sct.grab(self.target_monitor)
                    frame = np.array(screenshot)
                    
                    # Convert BGRA to RGB
                    if frame.shape[2] == 4:
                        frame = frame[:, :, :3]  # Remove alpha channel
                    
                    # Convert BGR to RGB (mss returns BGR)
                    frame = frame[:, :, ::-1]
                    
                    # Add cursor overlay if enabled
                    if self.capture_cursor:
                        monitor_offset = (self.target_monitor['left'], self.target_monitor['top'])
                        frame = self._draw_cursor_on_frame(frame, monitor_offset)
                    
                    timestamp = current_time
                    self.frames_captured += 1
                    last_capture_time = current_time
                    
                    # Add frame to queue
                    if not self.frame_queue.full():
                        self.frame_queue.put((frame, timestamp), block=False)
                    else:
                        # Remove oldest frame if queue is full
                        try:
                            self.frame_queue.get_nowait()
                            self.frame_queue.put((frame, timestamp), block=False)
                        except Empty:
                            pass
                    
                    # Call frame callback if set
                    if self.frame_callback:
                        try:
                            self.frame_callback(frame, timestamp)
                        except Exception as e:
                            self.logger.error(f"Error in frame callback: {e}")
                    
                except Exception as e:
                    self.logger.error(f"Error capturing frame: {e}")
                    time.sleep(0.01)  # Brief pause on error
                    
        except Exception as e:
            self.logger.error(f"Fatal error in capture loop: {e}")
        finally:
            # Clean up thread-local mss instance
            try:
                thread_sct.close()
            except:
                pass
            self.logger.debug("Capture loop ended")
    
    def get_frame(self, timeout: float = 0.1) -> Optional[Tuple[np.ndarray, float]]:
        """Get the next available frame from the queue."""
        try:
            return self.frame_queue.get(timeout=timeout)
        except Empty:
            return None
    
    def capture_single_frame(self, monitor_index: int = 1) -> Optional[np.ndarray]:
        """Capture a single frame without starting continuous capture."""
        try:
            if monitor_index >= len(self.monitors):
                monitor_index = 1
            
            monitor = self.monitors[monitor_index]
            screenshot = self.sct.grab(monitor)
            frame = np.array(screenshot)
            
            # Convert BGRA to RGB
            if frame.shape[2] == 4:
                frame = frame[:, :, :3]
            
            # Convert BGR to RGB
            frame = frame[:, :, ::-1]
            
            return frame
            
        except Exception as e:
            self.logger.error(f"Error capturing single frame: {e}")
            return None
    
    def get_screen_resolution(self, monitor_index: int = 1) -> Tuple[int, int]:
        """Get the resolution of specified monitor."""
        try:
            if monitor_index >= len(self.monitors):
                monitor_index = 1
            
            monitor = self.monitors[monitor_index]
            width = monitor['width']
            height = monitor['height']
            return (width, height)
            
        except Exception as e:
            self.logger.error(f"Error getting screen resolution: {e}")
            return (1920, 1080)  # Default resolution
    
    def get_capture_stats(self) -> dict:
        """Get capture performance statistics."""
        if self.start_time == 0:
            return {'status': 'not_started'}
        
        current_time = time.time()
        duration = current_time - self.start_time
        avg_fps = self.frames_captured / duration if duration > 0 else 0
        
        return {
            'status': 'capturing' if self.is_capturing else 'stopped',
            'frames_captured': self.frames_captured,
            'duration': duration,
            'average_fps': avg_fps,
            'target_fps': self.settings.fps,
            'queue_size': self.frame_queue.qsize(),
            'queue_max_size': self.frame_queue.maxsize
        }
    
    def cleanup(self):
        """Clean up resources."""
        try:
            self.stop_capture()
            if hasattr(self.sct, 'close'):
                self.sct.close()
            self.logger.info("Screen capture cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")