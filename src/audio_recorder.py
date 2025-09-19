"""Audio recording module for Pinpoint Capture screen recorder application."""

import sounddevice as sd
import numpy as np
import threading
import queue
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
import wave


class AudioRecorder:
    """Handles microphone audio recording."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.is_recording = False
        self.audio_queue = queue.Queue()
        self.recording_thread = None
        self.sample_rate = 44100
        self.channels = 1
        self.dtype = np.float32
        self.device_id = None
        self.audio_data = []
        self._lock = threading.Lock()
    
    @staticmethod
    def get_audio_devices() -> List[Dict[str, Any]]:
        """Get list of available audio input devices."""
        try:
            devices = sd.query_devices()
            input_devices = []
            
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    input_devices.append({
                        'id': i,
                        'name': device['name'],
                        'channels': device['max_input_channels'],
                        'sample_rate': device['default_samplerate']
                    })
            
            return input_devices
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to get audio devices: {e}")
            return []
    
    @staticmethod
    def get_default_device_id() -> Optional[int]:
        """Get the default audio input device ID."""
        try:
            default_device = sd.query_devices(kind='input')
            devices = sd.query_devices()
            
            for i, device in enumerate(devices):
                if device['name'] == default_device['name']:
                    return i
            return None
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to get default device: {e}")
            return None
    
    def set_device(self, device_id: Optional[int]):
        """Set the audio input device."""
        if device_id is not None:
            try:
                # Test if device is valid
                device_info = sd.query_devices(device_id)
                if device_info['max_input_channels'] > 0:
                    self.device_id = device_id
                    self.logger.info(f"Audio device set to: {device_info['name']}")
                else:
                    self.logger.warning(f"Device {device_id} has no input channels")
            except Exception as e:
                self.logger.error(f"Failed to set audio device {device_id}: {e}")
        else:
            self.device_id = None
    
    def start_recording(self) -> bool:
        """Start audio recording."""
        if self.is_recording:
            self.logger.warning("Audio recording already in progress")
            return False
        
        try:
            with self._lock:
                self.audio_data.clear()
                self.is_recording = True
            
            self.recording_thread = threading.Thread(target=self._recording_worker)
            self.recording_thread.daemon = True
            self.recording_thread.start()
            
            self.logger.info("Audio recording started")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start audio recording: {e}")
            self.is_recording = False
            return False
    
    def stop_recording(self) -> bool:
        """Stop audio recording."""
        if not self.is_recording:
            return True
        
        try:
            with self._lock:
                self.is_recording = False
            
            if self.recording_thread and self.recording_thread.is_alive():
                self.recording_thread.join(timeout=2.0)
            
            self.logger.info("Audio recording stopped")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to stop audio recording: {e}")
            return False
    
    def save_audio(self, output_path: str) -> bool:
        """Save recorded audio to WAV file."""
        if not self.audio_data:
            self.logger.warning("No audio data to save")
            return False
        
        try:
            # Convert list of arrays to single array
            audio_array = np.concatenate(self.audio_data)
            
            # Convert float32 to int16 for WAV format
            audio_int16 = (audio_array * 32767).astype(np.int16)
            
            # Save as WAV file
            with wave.open(output_path, 'wb') as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(2)  # 2 bytes for int16
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(audio_int16.tobytes())
            
            self.logger.info(f"Audio saved to: {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to save audio: {e}")
            return False
    
    def get_audio_data(self) -> np.ndarray:
        """Get the recorded audio data as numpy array."""
        if not self.audio_data:
            return np.array([], dtype=self.dtype)
        return np.concatenate(self.audio_data)
    
    def clear_audio_data(self):
        """Clear the recorded audio data."""
        with self._lock:
            self.audio_data.clear()
    
    def _recording_worker(self):
        """Worker thread for audio recording."""
        try:
            def audio_callback(indata, frames, time, status):
                if status:
                    self.logger.warning(f"Audio callback status: {status}")
                
                if self.is_recording:
                    # Copy audio data to avoid issues with the callback buffer
                    audio_chunk = indata.copy()
                    with self._lock:
                        self.audio_data.append(audio_chunk.flatten())
            
            # Start the audio stream
            with sd.InputStream(
                device=self.device_id,
                channels=self.channels,
                samplerate=self.sample_rate,
                dtype=self.dtype,
                callback=audio_callback,
                blocksize=1024
            ):
                while self.is_recording:
                    sd.sleep(100)  # Sleep for 100ms
                    
        except Exception as e:
            self.logger.error(f"Audio recording worker error: {e}")
            with self._lock:
                self.is_recording = False
    
    def is_device_available(self, device_id: int) -> bool:
        """Check if a specific audio device is available."""
        try:
            device_info = sd.query_devices(device_id)
            return device_info['max_input_channels'] > 0
        except:
            return False
    
    def get_recording_duration(self) -> float:
        """Get the duration of recorded audio in seconds."""
        if not self.audio_data:
            return 0.0
        
        total_samples = sum(len(chunk) for chunk in self.audio_data)
        return total_samples / self.sample_rate
    
    def cleanup(self):
        """Clean up audio recorder resources."""
        try:
            if self.is_recording:
                self.stop_recording()
            
            self.clear_audio_data()
            self.logger.info("Audio recorder cleaned up")
            
        except Exception as e:
            self.logger.error(f"Error during audio recorder cleanup: {e}")