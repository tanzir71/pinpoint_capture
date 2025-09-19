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
import numpy as np
import cv2
import mss
from pathlib import Path
from xml.etree import ElementTree as ET
import re
import os

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
        
        # Custom cursor settings
        self.custom_cursor_path = Path("cursor-alt.svg")
        self.cursor_image = None
        self.cursor_size = (32, 32)  # Default cursor size
        
        # Cache cursor images to avoid repeated rendering
        self.cursor_cache = {}
        self.last_cursor_pos = None
        self.cursor_moved = True
        
        # Use higher resolution cursor for better quality
        self.cursor_size = (64, 64)  # Increased from 32x32 to 64x64
        self.cursor_scale_factor = 2.0  # Scale factor for rendering
        
        self._load_custom_cursor()
        
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
    
    def _load_custom_cursor(self):
        """Load and prepare custom SVG cursor for rendering."""
        try:
            if not self.custom_cursor_path.exists():
                self.logger.warning(f"Custom cursor file not found: {self.custom_cursor_path}")
                return
            
            # Parse SVG file
            tree = ET.parse(self.custom_cursor_path)
            root = tree.getroot()
            
            # Get viewBox dimensions
            viewbox = root.get('viewBox', '0 0 540 540')
            _, _, width, height = map(float, viewbox.split())
            
            # Scale to higher resolution cursor size (64x64)
            scale_x = 64 / width
            scale_y = 64 / height
            
            # Create cursor image array (RGBA format)
            cursor_w, cursor_h = self.cursor_size
            self.cursor_image = np.zeros((cursor_h, cursor_w, 4), dtype=np.uint8)
            
            # Find path element
            path_elem = root.find('.//{http://www.w3.org/2000/svg}path')
            if path_elem is None:
                path_elem = root.find('.//path')  # Try without namespace
            
            if path_elem is not None:
                # Parse path data (simplified - handles basic commands)
                path_data = path_elem.get('d', '')
                
                # Extract coordinates using regex
                coords = re.findall(r'[-+]?\d*\.?\d+', path_data)
                if len(coords) >= 4:
                    # Convert to points and scale
                    points = []
                    for i in range(0, len(coords)-1, 2):
                        x = float(coords[i]) * scale_x
                        y = float(coords[i+1]) * scale_y
                        points.append([int(x), int(y)])
                    
                    if len(points) >= 3:
                        points = np.array(points, dtype=np.float32)
                        
                        # Create a temporary high-resolution image for anti-aliasing
                        temp_size = 128  # Even higher resolution for rendering
                        temp_cursor = np.zeros((temp_size, temp_size, 4), dtype=np.uint8)
                        
                        # Scale points to temp resolution
                        temp_scale = temp_size / 64
                        temp_points = (points * temp_scale).astype(np.int32)
                        
                        # Draw with anti-aliasing using cv2.fillPoly with LINE_AA
                        cv2.fillPoly(temp_cursor, [temp_points], (0, 0, 0, 255), lineType=cv2.LINE_AA)
                        
                        # Create white fill (slightly smaller)
                        center = np.mean(temp_points, axis=0)
                        shrunk_points = center + (temp_points - center) * 0.85
                        shrunk_points = shrunk_points.astype(np.int32)
                        cv2.fillPoly(temp_cursor, [shrunk_points], (255, 255, 255, 255), lineType=cv2.LINE_AA)
                        
                        # Resize down to final cursor size with anti-aliasing
                        self.cursor_image = cv2.resize(temp_cursor, (64, 64), interpolation=cv2.INTER_AREA)
            
            # Set alpha channel for non-transparent pixels
            mask = np.any(self.cursor_image[:, :, :3] > 0, axis=2)
            self.cursor_image[:, :, 3] = mask.astype(np.uint8) * 255
            
            self.logger.info("Custom cursor loaded successfully from SVG")
            
        except Exception as e:
            self.logger.error(f"Error loading custom cursor from SVG: {e}")
            # Fallback to simple cursor shape
            cursor_w, cursor_h = self.cursor_size
            self.cursor_image = np.zeros((cursor_h, cursor_w, 4), dtype=np.uint8)
            
            cursor_points = np.array([
                [2, 2], [2, 28], [8, 22], [14, 30], [18, 26], [12, 18], [26, 18]
            ], np.int32)
            
            temp_cursor = np.zeros((cursor_h, cursor_w, 3), dtype=np.uint8)
            cv2.fillPoly(temp_cursor, [cursor_points], (0, 0, 0))
            cursor_fill = cursor_points.copy()
            cursor_fill = np.maximum(cursor_fill - 1, 0)
            cv2.fillPoly(temp_cursor, [cursor_fill], (255, 255, 255))
            
            self.cursor_image[:, :, :3] = temp_cursor
            mask = np.any(temp_cursor > 0, axis=2)
            self.cursor_image[:, :, 3] = mask.astype(np.uint8) * 255
    
    def _get_cursor_info(self) -> Optional[Tuple[int, int, int, int]]:
        """Get cursor position and size using Windows API with caching."""
        try:
            # Cache cursor info to reduce API calls
            current_time = time.time()
            if hasattr(self, '_last_cursor_check') and (current_time - self._last_cursor_check) < 0.008:  # ~120 FPS limit
                if hasattr(self, '_cached_cursor_info'):
                    return self._cached_cursor_info
            
            cursor_info = CURSORINFO()
            cursor_info.cbSize = ctypes.sizeof(CURSORINFO)
            
            if not self.user32.GetCursorInfo(ctypes.byref(cursor_info)):
                self._cached_cursor_info = None
                self._last_cursor_check = current_time
                return None
            
            if cursor_info.flags != CURSOR_SHOWING:
                self._cached_cursor_info = None
                self._last_cursor_check = current_time
                return None
            
            # Get cursor position
            x, y = cursor_info.ptScreenPos.x, cursor_info.ptScreenPos.y
            
            # Get cursor icon info for hotspot (cache this too)
            if not hasattr(self, '_cursor_hotspot_cache') or self._cursor_hotspot_cache[0] != cursor_info.hCursor:
                icon_info = ICONINFO()
                if self.user32.GetIconInfo(cursor_info.hCursor, ctypes.byref(icon_info)):
                    hotspot_x, hotspot_y = icon_info.xHotspot, icon_info.yHotspot
                    self._cursor_hotspot_cache = (cursor_info.hCursor, hotspot_x, hotspot_y)
                    
                    # Clean up bitmap handles
                    if icon_info.hbmMask:
                        self.gdi32.DeleteObject(icon_info.hbmMask)
                    if icon_info.hbmColor:
                        self.gdi32.DeleteObject(icon_info.hbmColor)
                else:
                    self._cursor_hotspot_cache = (cursor_info.hCursor, 0, 0)
            
            # Apply cached hotspot
            _, hotspot_x, hotspot_y = self._cursor_hotspot_cache
            x -= hotspot_x
            y -= hotspot_y
            
            # Use scaled cursor size
            cursor_size = int(64 // self.cursor_scale_factor)
            result = (x, y, cursor_size, cursor_size)
            
            # Cache the result
            self._cached_cursor_info = result
            self._last_cursor_check = current_time
            
            return result
            
        except Exception as e:
            self.logger.debug(f"Error getting cursor info: {e}")
            self._cached_cursor_info = None
            self._last_cursor_check = current_time if 'current_time' in locals() else time.time()
            return None
    
    def _draw_cursor_on_frame(self, frame: np.ndarray, monitor_offset: Tuple[int, int]) -> np.ndarray:
        """Draw cursor on the captured frame with optimized rendering."""
        if not self.capture_cursor:
            return frame
        
        try:
            cursor_info = self._get_cursor_info()
            if not cursor_info:
                return frame
            
            cursor_x, cursor_y, cursor_w, cursor_h = cursor_info
            monitor_x, monitor_y = monitor_offset
            
            # Convert screen coordinates to frame coordinates
            frame_x = cursor_x - monitor_x
            frame_y = cursor_y - monitor_y
            
            # Early bounds check to avoid unnecessary processing
            frame_height, frame_width = frame.shape[:2]
            if (frame_x + cursor_w < 0 or frame_x >= frame_width or 
                frame_y + cursor_h < 0 or frame_y >= frame_height):
                return frame
            
            # Check if cursor moved significantly (reduce sensitivity for smoother rendering)
            current_pos = (frame_x, frame_y)
            if (self.last_cursor_pos is not None and 
                abs(current_pos[0] - self.last_cursor_pos[0]) < 2 and 
                abs(current_pos[1] - self.last_cursor_pos[1]) < 2):
                # Cursor moved less than 2 pixels, skip expensive operations
                pass
            else:
                self.cursor_moved = True
                self.last_cursor_pos = current_pos
            
            # Draw cursor on frame (always draw for smooth movement)
            if self.cursor_image is not None:
                try:
                    self._draw_custom_cursor(frame, frame_x, frame_y)
                except Exception as e:
                    self.logger.error(f"Error drawing custom cursor: {e}")
                    # Fall back to default cursor
                    self._draw_default_cursor(frame, frame_x, frame_y)
            else:
                # Fall back to default cursor
                self._draw_default_cursor(frame, frame_x, frame_y)
                
        except Exception as e:
            self.logger.error(f"Error drawing cursor on frame: {e}")
            
        return frame
    
    def _draw_custom_cursor(self, frame: np.ndarray, frame_x: int, frame_y: int):
        """Draw the custom cursor on the frame with optimized rendering."""
        if self.cursor_image is None:
            return
        
        cursor_h, cursor_w = self.cursor_image.shape[:2]
        frame_h, frame_w = frame.shape[:2]
        
        # Scale cursor size for display (render at higher res, display smaller)
        display_w = int(cursor_w // self.cursor_scale_factor)
        display_h = int(cursor_h // self.cursor_scale_factor)
        
        # Calculate the region where the cursor will be drawn
        start_x = max(0, frame_x)
        start_y = max(0, frame_y)
        end_x = min(frame_w, frame_x + display_w)
        end_y = min(frame_h, frame_y + display_h)
        
        if start_x >= end_x or start_y >= end_y:
            return  # Cursor is completely outside frame
        
        # Create cache key for this cursor position and size
        cache_key = f"cursor_{frame_x}_{frame_y}_{display_w}_{display_h}"
        
        # Check if we have a cached scaled cursor for this size
        if cache_key not in self.cursor_cache:
            # Scale down the high-res cursor with anti-aliasing
            scaled_cursor = cv2.resize(self.cursor_image, (display_w, display_h), 
                                     interpolation=cv2.INTER_AREA)
            self.cursor_cache[cache_key] = scaled_cursor
            
            # Limit cache size to prevent memory issues
            if len(self.cursor_cache) > 20:
                # Remove oldest entries
                oldest_keys = list(self.cursor_cache.keys())[:5]
                for key in oldest_keys:
                    del self.cursor_cache[key]
        
        scaled_cursor = self.cursor_cache[cache_key]
        
        # Calculate corresponding cursor region
        cursor_start_x = max(0, -frame_x)
        cursor_start_y = max(0, -frame_y)
        cursor_end_x = cursor_start_x + (end_x - start_x)
        cursor_end_y = cursor_start_y + (end_y - start_y)
        
        # Extract the cursor region
        cursor_region = scaled_cursor[cursor_start_y:cursor_end_y, cursor_start_x:cursor_end_x]
        frame_region = frame[start_y:end_y, start_x:end_x]
        
        # Optimized alpha blending
        if cursor_region.shape[2] == 4 and cursor_region.size > 0:  # RGBA cursor
            alpha = cursor_region[:, :, 3:4].astype(np.float32) / 255.0
            cursor_rgb = cursor_region[:, :, :3].astype(np.float32)
            frame_rgb = frame_region.astype(np.float32)
            
            # Vectorized alpha blending
            blended = frame_rgb * (1 - alpha) + cursor_rgb * alpha
            frame[start_y:end_y, start_x:end_x] = blended.astype(np.uint8)
        elif cursor_region.size > 0:  # RGB cursor
            frame[start_y:end_y, start_x:end_x] = cursor_region
    
    def _draw_default_cursor(self, frame: np.ndarray, frame_x: int, frame_y: int):
        """Draw the default cursor matching the SVG design."""
        # Define cursor points based on the SVG path (scaled down and simplified)
        # The SVG shows a modern pointer with a curved tail
        cursor_points = np.array([
            [0, 0],      # Top point
            [3, 12],     # Left side of arrow
            [8, 10],     # Inner left point
            [10, 16],    # Tail start
            [14, 18],    # Tail curve
            [16, 14],    # Tail end
            [12, 12],    # Inner right point
            [18, 8],     # Right side of arrow
            [8, 8]       # Inner point
        ], np.int32)
        
        # Offset points to cursor position
        cursor_points[:, 0] += frame_x
        cursor_points[:, 1] += frame_y
        
        # Ensure all points are within frame bounds
        cursor_points[:, 0] = np.clip(cursor_points[:, 0], 0, frame.shape[1] - 1)
        cursor_points[:, 1] = np.clip(cursor_points[:, 1], 0, frame.shape[0] - 1)
        
        # Draw black outline (stroke)
        cv2.fillPoly(frame, [cursor_points], (5, 5, 5))  # Dark stroke color
        
        # Create slightly smaller fill points for white interior
        fill_points = cursor_points.copy()
        # Shrink the shape slightly for the fill
        center_x = np.mean(fill_points[:, 0])
        center_y = np.mean(fill_points[:, 1])
        fill_points[:, 0] = center_x + (fill_points[:, 0] - center_x) * 0.8
        fill_points[:, 1] = center_y + (fill_points[:, 1] - center_y) * 0.8
        fill_points = fill_points.astype(np.int32)
        
        # Ensure fill points are within bounds
        fill_points[:, 0] = np.clip(fill_points[:, 0], 0, frame.shape[1] - 1)
        fill_points[:, 1] = np.clip(fill_points[:, 1], 0, frame.shape[0] - 1)
        
        # Draw white fill
        cv2.fillPoly(frame, [fill_points], (255, 255, 255))
    
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
        """Optimized main capture loop running in separate thread."""
        target_fps = self.settings.fps
        frame_interval = 1.0 / target_fps
        last_capture_time = 0
        frame_count = 0
        last_fps_time = time.time()
        
        # Create mss instance for this thread to avoid threading issues
        thread_sct = mss.mss()
        
        # Pre-calculate monitor offset for cursor drawing
        monitor_offset = (self.target_monitor['left'], self.target_monitor['top'])
        
        try:
            while self.is_capturing:
                current_time = time.time()
                
                # Precise frame rate control
                time_since_last = current_time - last_capture_time
                if time_since_last < frame_interval:
                    sleep_time = frame_interval - time_since_last
                    if sleep_time > 0.001:  # Only sleep if meaningful
                        time.sleep(sleep_time)
                    continue
                
                # Capture frame
                try:
                    screenshot = thread_sct.grab(self.target_monitor)
                    
                    # Optimized frame conversion with direct buffer access
                    if hasattr(screenshot, 'raw') and screenshot.raw:
                        # Direct conversion from BGRA to RGB using raw buffer
                        frame = np.frombuffer(screenshot.raw, dtype=np.uint8)
                        frame = frame.reshape((screenshot.height, screenshot.width, 4))
                        # Direct slice to RGB (remove alpha) and reorder BGR to RGB
                        frame = frame[:, :, [2, 1, 0]]  # BGR to RGB by reordering channels
                    else:
                        # Fallback conversion for compatibility
                        frame = np.array(screenshot)
                        if frame.shape[2] == 4:
                            frame = frame[:, :, :3]  # Remove alpha channel
                        frame = frame[:, :, ::-1]  # Convert BGR to RGB
                    
                    # Ensure frame is contiguous and correct type for optimal processing
                    if not frame.flags['C_CONTIGUOUS'] or frame.dtype != np.uint8:
                        frame = np.ascontiguousarray(frame, dtype=np.uint8)
                    
                    # Add cursor overlay if enabled (with pre-calculated offset)
                    if self.capture_cursor:
                        frame = self._draw_cursor_on_frame(frame, monitor_offset)
                    
                    timestamp = current_time
                    self.frames_captured += 1
                    last_capture_time = current_time
                    frame_count += 1
                    
                    # Efficient queue management
                    try:
                        if not self.frame_queue.full():
                            self.frame_queue.put_nowait((frame, timestamp))
                        else:
                            # Drop oldest frame if queue is full
                            try:
                                self.frame_queue.get_nowait()
                                self.frame_queue.put_nowait((frame, timestamp))
                            except Empty:
                                pass
                    except:
                        pass  # Continue if queue operations fail
                    
                    # Call frame callback if set
                    if self.frame_callback:
                        try:
                            self.frame_callback(frame, timestamp)
                        except Exception as e:
                            self.logger.error(f"Error in frame callback: {e}")
                    
                    # Log FPS every 2 seconds to reduce overhead
                    if current_time - last_fps_time >= 2.0:
                        fps = frame_count / (current_time - last_fps_time)
                        self.logger.debug(f"Capture FPS: {fps:.1f}")
                        frame_count = 0
                        last_fps_time = current_time
                    
                except Exception as e:
                    self.logger.error(f"Error capturing frame: {e}")
                    time.sleep(0.005)  # Shorter pause on error
                    
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