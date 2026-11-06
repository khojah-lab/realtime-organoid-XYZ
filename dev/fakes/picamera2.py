"""Stand-in for picamera2 that produces a synthetic microscope-like frame."""
import time

import numpy as np
import cv2


class _FakeRequest:
    def __init__(self, frame):
        self._frame = frame

    def make_array(self, stream_name):
        return self._frame

    def release(self):
        pass


class Picamera2:
    def create_video_configuration(self, main, **kwargs):
        self._width, self._height = main["size"]
        return {"main": main}

    def configure(self, config):
        pass

    def start(self):
        self._start_time = time.time()

    def capture_request(self):
        elapsed = time.time() - self._start_time
        frame = np.full((self._height, self._width, 3), 40, np.uint8)
        for index in range(6):
            angle = elapsed * 0.3 + index * 1.05
            center = (
                int(self._width * (0.5 + 0.3 * np.cos(angle + index))),
                int(self._height * (0.5 + 0.3 * np.sin(angle * 1.3))),
            )
            cv2.circle(frame, center, 40 + 8 * index, (120, 200, 160), -1)
            cv2.circle(frame, center, 40 + 8 * index, (200, 255, 220), 3)
        cv2.putText(frame, "FAKE CAMERA", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        return _FakeRequest(frame)
