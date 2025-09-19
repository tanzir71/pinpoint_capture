"""Mouse event handler for Pinpoint Capture application."""

import threading
import time
import logging
from typing import Optional, Callable, List
import ctypes
import ctypes.wintypes
from ctypes import wintypes

from .models import ClickEvent, RecordingSettings

# Add pynput fallback import
try:
    from pynput import mouse as pynput_mouse
except Exception:
    pynput_mouse = None


# Windows API constants
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
HC_ACTION = 0
WH_MOUSE_LL = 14
# Virtual-Key codes for polling-based detection
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04

# Hook procedure type
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_long)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]

class MouseEventHandler:
    """Handles mouse click detection and event processing using Windows API."""
    
    def __init__(self, settings: RecordingSettings):
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        
        # Event tracking
        self.is_monitoring = False
        self.click_events: List[ClickEvent] = []
        self.hook = None
        self.hook_proc = None
        
        # Callbacks
        self.click_callback: Optional[Callable[[ClickEvent], None]] = None
        
        # Click detection settings
        self.sensitivity = settings.click_detection_sensitivity
        self.last_click_time = 0
        self.min_click_interval = 0.1  # Minimum time between clicks (debounce)
        
        # Screen resolution for coordinate validation
        self.screen_resolution = (1920, 1080)  # Will be updated by screen capture
        
        # Windows API setup
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

        # NEW: pynput listener fallback
        self.listener = None
        self.use_pynput = pynput_mouse is not None

        # NEW: polling-based detection fallback (preferred on Windows/Python 3.13)
        self.poll_thread: Optional[threading.Thread] = None
        self._prev_left = False
        self._prev_right = False
        self._prev_middle = False

        self.logger.info("Mouse event handler initialized with Windows API")
    
    def set_screen_resolution(self, resolution: tuple):
        """Update screen resolution for coordinate validation."""
        self.screen_resolution = resolution
        self.logger.debug(f"Screen resolution updated to {resolution}")
    
    def set_click_callback(self, callback: Callable[[ClickEvent], None]):
        """Set callback function to receive click events."""
        self.click_callback = callback
    
    def start_monitoring(self) -> bool:
        """Start monitoring mouse clicks using polling-based detection (robust on Windows)."""
        if self.is_monitoring:
            self.logger.warning("Mouse monitoring already active")
            return False
        
        try:
            self.is_monitoring = True
            self.click_events.clear()

            # Prefer robust polling-based detection to avoid pynput issues on some Python/Windows combos
            def _start_poll_thread():
                self.poll_thread = threading.Thread(target=self._poll_mouse, daemon=True, name="MousePollThread")
                self.poll_thread.start()
                self.logger.info("Mouse monitoring started (polling-based)")

            _start_poll_thread()
            return True
            
        except Exception as e:
            self.logger.error(f"Error starting mouse monitoring: {e}")
            self.is_monitoring = False
            return False

    # NEW: pynput click callback
    def _on_pynput_click(self, x, y, button, pressed):
        if not pressed or not self.is_monitoring:
            return

        current_time = time.time()
        if current_time - self.last_click_time < self.min_click_interval:
            return

        # Determine button type
        try:
            button_str = str(button).split('.')[-1].lower()
            if 'left' in button_str:
                button_str = 'left'
            elif 'right' in button_str:
                button_str = 'right'
            elif 'middle' in button_str:
                button_str = 'middle'
            else:
                button_str = 'unknown'
        except Exception:
            button_str = 'unknown'

        # Create click event (global coordinates); resolution is set by controller
        click_event = ClickEvent.create_now(int(x), int(y), button_str, self.screen_resolution)
        self.click_events.append(click_event)
        self.last_click_time = current_time

        if self.click_callback:
            def call_callback():
                try:
                    self.click_callback(click_event)
                except Exception as e:
                    self.logger.error(f"Error in click callback: {e}")
            threading.Thread(target=call_callback, daemon=True).start()
    
    def stop_monitoring(self) -> bool:
        """Stop monitoring mouse clicks."""
        if not self.is_monitoring:
            return True
        
        try:
            self.is_monitoring = False

            # Stop polling thread
            if self.poll_thread and self.poll_thread.is_alive():
                self.poll_thread.join(timeout=1.0)
                self.poll_thread = None
            
            # Stop pynput listener if it was ever started
            if self.listener is not None:
                try:
                    self.listener.stop()
                except Exception:
                    pass
                finally:
                    self.listener = None
            
            if self.hook:
                try:
                    self.user32.UnhookWindowsHookEx(self.hook)
                except Exception as e:
                    self.logger.debug(f"Error unhooking mouse hook: {e}")
                finally:
                    self.hook = None
                    self.hook_proc = None
            
            self.logger.info(f"Mouse monitoring stopped. Captured {len(self.click_events)} clicks")
            return True
            
        except Exception as e:
            self.logger.error(f"Error stopping mouse monitoring: {e}")
            return False
    
    def _low_level_mouse_proc(self, nCode: int, wParam: int, lParam: int) -> int:
        """Low-level mouse hook procedure."""
        if nCode >= HC_ACTION and self.is_monitoring:
            if wParam in [WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN]:
                # Get mouse data
                mouse_struct = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                x, y = mouse_struct.pt.x, mouse_struct.pt.y
                
                current_time = time.time()
                
                # Debounce clicks
                if current_time - self.last_click_time < self.min_click_interval:
                    return self.user32.CallNextHookEx(self.hook, nCode, wParam, lParam)
                
                # Validate coordinates
                if not (0 <= x <= self.screen_resolution[0] and 0 <= y <= self.screen_resolution[1]):
                    return self.user32.CallNextHookEx(self.hook, nCode, wParam, lParam)
                
                # Determine button type
                if wParam == WM_LBUTTONDOWN:
                    button_str = "left"
                elif wParam == WM_RBUTTONDOWN:
                    button_str = "right"
                elif wParam == WM_MBUTTONDOWN:
                    button_str = "middle"
                else:
                    button_str = "unknown"
                
                # Create click event
                click_event = ClickEvent(
                    timestamp=current_time,
                    x=x,
                    y=y,
                    button=button_str,
                    screen_resolution=self.screen_resolution  # ensure required field is set
                )
                
                # Store the event
                self.click_events.append(click_event)
                self.last_click_time = current_time
                
                self.logger.debug(f"Click detected: {button_str} at ({x}, {y})")
                
                # Call callback if set
                if self.click_callback:
                    def call_callback():
                        try:
                            self.click_callback(click_event)
                        except Exception as e:
                            self.logger.error(f"Error in click callback: {e}")
                    
                    # Run callback in separate thread to avoid blocking
                    callback_thread = threading.Thread(target=call_callback, daemon=True)
                    callback_thread.start()
        
        return self.user32.CallNextHookEx(self.hook, nCode, wParam, lParam)
    
    def _should_process_click(self, x: int, y: int, button: str) -> bool:
        """Apply sensitivity and filtering logic to determine if click should be processed."""
        # For now, process all valid clicks
        # Future enhancements could include:
        # - Ignore clicks in certain screen areas
        # - Filter based on click patterns
        # - Apply machine learning for smart filtering
        
        # Basic sensitivity check - ignore very rapid clicks in same location
        if len(self.click_events) > 0:
            last_click = self.click_events[-1]
            time_diff = time.time() - last_click.timestamp
            distance = ((x - last_click.x) ** 2 + (y - last_click.y) ** 2) ** 0.5
            
            # If click is very close to previous and very recent, apply sensitivity
            if time_diff < 0.5 and distance < 10:
                return time_diff > (1.0 - self.sensitivity) * 0.5
        
        return True
    
    def get_recent_clicks(self, seconds: float = 5.0) -> List[ClickEvent]:
        """Get clicks from the last N seconds."""
        current_time = time.time()
        cutoff_time = current_time - seconds
        
        return [click for click in self.click_events 
                if click.timestamp >= cutoff_time]
    
    def get_clicks_in_range(self, start_time: float, end_time: float) -> List[ClickEvent]:
        """Get clicks within a specific time range."""
        return [click for click in self.click_events 
                if start_time <= click.timestamp <= end_time]
    
    def clear_click_history(self):
        """Clear all stored click events."""
        self.click_events.clear()
        self.logger.debug("Click history cleared")
    
    def get_click_statistics(self) -> dict:
        """Get statistics about captured clicks."""
        if not self.click_events:
            return {
                'total_clicks': 0,
                'clicks_per_button': {},
                'average_interval': 0,
                'monitoring_duration': 0
            }
        
        # Count clicks by button
        button_counts = {}
        for click in self.click_events:
            button_counts[click.button] = button_counts.get(click.button, 0) + 1
        
        # Calculate average interval
        if len(self.click_events) > 1:
            intervals = []
            for i in range(1, len(self.click_events)):
                interval = self.click_events[i].timestamp - self.click_events[i-1].timestamp
                intervals.append(interval)
            avg_interval = sum(intervals) / len(intervals)
        else:
            avg_interval = 0
        
        # Calculate monitoring duration
        if self.click_events:
            duration = self.click_events[-1].timestamp - self.click_events[0].timestamp
        else:
            duration = 0
        
        return {
            'total_clicks': len(self.click_events),
            'clicks_per_button': button_counts,
            'average_interval': avg_interval,
            'monitoring_duration': duration,
            'clicks_per_minute': len(self.click_events) / (duration / 60) if duration > 0 else 0
        }
    
    def update_settings(self, settings: RecordingSettings):
        """Update mouse handler settings."""
        self.settings = settings
        self.sensitivity = settings.click_detection_sensitivity
        self.logger.debug(f"Mouse handler settings updated, sensitivity: {self.sensitivity}")
    
    def is_active(self) -> bool:
        """Check if mouse monitoring is currently active."""
        return self.is_monitoring and (self.hook is not None or self.listener is not None or self.poll_thread is not None)
    
    def cleanup(self):
        """Clean up resources."""
        try:
            self.stop_monitoring()
            self.logger.info("Mouse handler cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    # --- Internal helpers ---
    def _poll_mouse(self):
        """Polling loop for mouse button down events using Win32 GetAsyncKeyState and GetCursorPos."""
        # Initialize previous states
        self._prev_left = False
        self._prev_right = False
        self._prev_middle = False
        POINT_STRUCT = POINT
        pt = POINT_STRUCT()

        while self.is_monitoring:
            try:
                # Check button states
                left_pressed = (self.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0
                right_pressed = (self.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000) != 0
                middle_pressed = (self.user32.GetAsyncKeyState(VK_MBUTTON) & 0x8000) != 0

                # Edge detection: trigger on press down
                if left_pressed and not self._prev_left:
                    if self.user32.GetCursorPos(ctypes.byref(pt)):
                        self._emit_click(pt.x, pt.y, 'left')
                if right_pressed and not self._prev_right:
                    if self.user32.GetCursorPos(ctypes.byref(pt)):
                        self._emit_click(pt.x, pt.y, 'right')
                if middle_pressed and not self._prev_middle:
                    if self.user32.GetCursorPos(ctypes.byref(pt)):
                        self._emit_click(pt.x, pt.y, 'middle')

                # Update previous states
                self._prev_left = left_pressed
                self._prev_right = right_pressed
                self._prev_middle = middle_pressed

                # Polling interval
                time.sleep(0.01)
            except Exception as e:
                self.logger.debug(f"Mouse polling error: {e}")
                time.sleep(0.02)

    def _emit_click(self, x: int, y: int, button_str: str):
        """Create and dispatch a ClickEvent respecting debounce and resolution bounds."""
        current_time = time.time()
        if current_time - self.last_click_time < self.min_click_interval:
            return

        # Validate coordinates if resolution is known
        try:
            max_w, max_h = self.screen_resolution
            if not (0 <= x <= max_w + 10000 and 0 <= y <= max_h + 10000):
                # Allow coordinates larger than monitor (multi-monitor); they will be adjusted later
                pass
        except Exception:
            pass

        click_event = ClickEvent.create_now(int(x), int(y), button_str, self.screen_resolution)
        self.click_events.append(click_event)
        self.last_click_time = current_time

        if self.click_callback:
            try:
                self.click_callback(click_event)
            except Exception as e:
                self.logger.error(f"Error in click callback: {e}")