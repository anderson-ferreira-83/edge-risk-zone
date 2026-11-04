import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from app.detector import PersonDetector

MODEL = Path(__file__).resolve().parent.parent / "models" / "yolox_tiny.onnx"
SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "airplane.jpg"


def test_input_size_must_match_the_fixed_onnx_input():
    with pytest.raises(ValueError, match="exige entrada"):
        PersonDetector(MODEL, input_size=320)


class _SlowSession:
    """Envolve a sessão real e mede quantas inferências rodam ao mesmo tempo."""

    def __init__(self, real):
        self.real, self.active, self.peak, self.lock = real, 0, 0, threading.Lock()

    def run(self, *args, **kwargs):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)
        try:
            return self.real.run(*args, **kwargs)
        finally:
            with self.lock:
                self.active -= 1


@pytest.mark.parametrize("limit, expected_peak", [(1, 1), (3, 3)])
def test_concurrency_limit_is_respected(limit, expected_peak):
    detector = PersonDetector(MODEL, max_concurrent=limit)
    detector.session = _SlowSession(detector.session)
    image = Image.open(SAMPLE).convert("RGB")
    results = []
    threads = [threading.Thread(target=lambda: results.append(len(detector.detect(image).detections))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert detector.session.peak == expected_peak
    assert len(set(results)) == 1 and len(results) == 6  # mesmo resultado em todas as threads
