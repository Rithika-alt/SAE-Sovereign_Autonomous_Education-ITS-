"""Camera proctoring using OpenCV face detection in a background thread.

Two operating modes:
  • Server-side (direct webcam):  start_proctoring() / check_face_present() / stop_proctoring()
  • Browser-side (Streamlit):     detect_face_in_image_bytes(image_bytes) — processes a
                                  snapshot from st.camera_input() without touching the webcam.
"""

import io
import queue
import threading
import time
from typing import Optional

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Haar cascade path (bundled with OpenCV)
# ---------------------------------------------------------------------------

_CASCADE_PATH: str = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


class CameraProctor:
    """Detects face presence via OpenCV and tracks proctoring warnings.

    For use inside Streamlit, prefer detect_face_in_image_bytes() which
    operates on PIL/bytes snapshots from st.camera_input() rather than
    requiring a server-side webcam.  The background-thread path (start_proctoring
    / stop_proctoring) is available for CLI or non-browser contexts.
    """

    def __init__(self) -> None:
        """Initialise the cascade classifier and internal state."""
        self._cascade = cv2.CascadeClassifier(_CASCADE_PATH)
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_queue: queue.Queue = queue.Queue(maxsize=10)
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._warning_count: int = 0
        self._last_check_time: float = time.time()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Server-side webcam thread
    # ------------------------------------------------------------------

    def start_proctoring(self) -> None:
        """Start capturing webcam frames in a background daemon thread.

        Safe to call multiple times — subsequent calls are no-ops if already
        running.
        """
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self) -> None:
        """Internal capture loop: reads frames at ~10 fps until stopped."""
        self._cap = cv2.VideoCapture(0)
        if not self._cap.isOpened():
            self._running = False
            return

        while self._running:
            ret, frame = self._cap.read()
            if ret:
                if self._frame_queue.full():
                    try:
                        self._frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                self._frame_queue.put(frame)
            time.sleep(0.1)

        self._cap.release()

    def check_face_present(self) -> bool:
        """Return True if a face is detected in the latest captured webcam frame.

        Falls back to True (no false positives) when no frame is available.

        Returns:
            True if at least one face is detected, False otherwise.
        """
        self._last_check_time = time.time()

        if self._frame_queue.empty():
            return True  # no frame yet — optimistic default

        try:
            # Peek at the most recent frame without removing it
            with self._lock:
                frames = list(self._frame_queue.queue)
            frame = frames[-1] if frames else None
        except Exception:
            return True

        if frame is None:
            return True

        return self._detect_faces_in_frame(frame)

    def stop_proctoring(self) -> None:
        """Stop the background capture thread and release the webcam."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self._cap and self._cap.isOpened():
            self._cap.release()

    # ------------------------------------------------------------------
    # Browser-side: process st.camera_input() bytes
    # ------------------------------------------------------------------

    def detect_face_in_image_bytes(self, image_bytes: bytes) -> bool:
        """Detect faces in a JPEG/PNG image provided as raw bytes.

        Designed for use with st.camera_input() which returns a file-like
        object whose .read() gives image bytes.

        Args:
            image_bytes: Raw image bytes (JPEG or PNG).

        Returns:
            True if at least one face is detected, False otherwise.
        """
        self._last_check_time = time.time()
        try:
            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                return True
            return self._detect_faces_in_frame(frame)
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Warning management
    # ------------------------------------------------------------------

    def get_warning_count(self) -> int:
        """Return the current warning count.

        Returns:
            Integer warning count (starts at 0).
        """
        return self._warning_count

    def increment_warning(self) -> int:
        """Increment the warning counter and return the new value.

        Returns:
            Updated warning count after increment.
        """
        with self._lock:
            self._warning_count += 1
            return self._warning_count

    def reset_warnings(self) -> None:
        """Reset the warning counter to zero."""
        with self._lock:
            self._warning_count = 0

    def seconds_since_last_check(self) -> float:
        """Return seconds elapsed since the last face-check call."""
        return time.time() - self._last_check_time

    # ------------------------------------------------------------------
    # Internal face detection
    # ------------------------------------------------------------------

    def _detect_faces_in_frame(self, frame: np.ndarray) -> bool:
        """Run Haar cascade detection on a BGR frame.

        Only counts faces whose bounding box covers ≥ 5 % of the image area.
        This rejects faces on phone screens held at arm's length, which appear
        small in the frame, while accepting a real face sitting close to the camera.

        Args:
            frame: OpenCV BGR image array.

        Returns:
            True if at least one sufficiently-large face is detected.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        if len(faces) == 0:
            return False
        h, w = frame.shape[:2]
        img_area = h * w or 1
        for (_, _, fw, fh) in faces:
            if (fw * fh) / img_area >= 0.05:
                return True
        return False
