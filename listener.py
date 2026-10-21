"""
listener.py — Role 4 live listener.

Continuous microphone capture -> energy-gated state machine -> decode.

Design (matches the task plan):
  * A sounddevice callback only copies and queues blocks; it does no work.
  * A ring buffer of the last ~2 s means the start of a transmission is not
    lost when the energy gate opens a block or two late.
  * State machine: IDLE -> SYNC (gate opened) -> RECEIVING -> back to IDLE.
    The PoC uses the "record from gate-open until trailing silence, then decode
    the whole buffer" strategy named in the plan; true per-symbol streaming is
    a later optimization and the structure here leaves room for it.
  * Failures are counted and printed as one clean line, never garbled bytes.
"""

import time
import queue
import collections

import numpy as np

from common import (
    FS, SILENCE_HANG_S, GATE_MULTIPLIER, GATE_MIN_RMS, SYNC_TIMEOUT_S,
)
from decoder import decode

BLOCKSIZE = 1024
RING_SECONDS = 2.0


def rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(block ** 2))) if len(block) else 0.0


class FailureLog:
    """Tally of how often each failure type happens over a test session."""

    def __init__(self):
        self.counts = collections.Counter()
        self.ok = 0

    def record(self, result):
        if result.ok:
            self.ok += 1
        else:
            self.counts[result.reason] += 1

    def summary(self) -> str:
        parts = [f"ok={self.ok}"]
        for reason in ("no_preamble", "bad_header", "failed_auth"):
            parts.append(f"{reason}={self.counts[reason]}")
        return "  ".join(parts)


class Listener:
    """Owns the input stream, the state machine, and the decode handoff."""

    def __init__(self, device=None, on_message=None, verbose=True):
        self.device = device
        self.on_message = on_message or self._default_print
        self.verbose = verbose
        self.q: "queue.Queue[np.ndarray]" = queue.Queue()
        self.failures = FailureLog()
        self.noise_floor = GATE_MIN_RMS
        self._stop = False

    # --- audio callback: copy + queue only --------------------------------- #
    def _callback(self, indata, frames, time_info, status):
        if status and self.verbose:
            # Overflow here means dropped audio — worth knowing during OTA tests.
            print(f"[audio status] {status}")
        self.q.put(indata[:, 0].copy())

    # --- noise-floor calibration ------------------------------------------- #
    def _calibrate(self, seconds=1.0):
        """Measure the room noise floor from the first second of audio."""
        deadline = time.time() + seconds
        samples = []
        while time.time() < deadline:
            try:
                samples.append(self.q.get(timeout=0.5))
            except queue.Empty:
                break
        if samples:
            floor = rms(np.concatenate(samples))
            self.noise_floor = max(floor, GATE_MIN_RMS)
        if self.verbose:
            print(f"[calibrated] noise floor rms={self.noise_floor:.5f} "
                  f"gate={self.noise_floor * GATE_MULTIPLIER:.5f}")

    # --- main loop --------------------------------------------------------- #
    def run(self):
        import sounddevice as sd

        gate = self.noise_floor * GATE_MULTIPLIER
        ring = collections.deque(maxlen=int(RING_SECONDS * FS / BLOCKSIZE) + 1)

        state = "IDLE"
        working = []                       # blocks accumulated during a reception
        silence_run = 0.0                  # seconds of trailing silence seen
        sync_deadline = 0.0
        block_seconds = BLOCKSIZE / FS

        with sd.InputStream(samplerate=FS, channels=1, dtype="float32",
                            blocksize=BLOCKSIZE, device=self.device,
                            callback=self._callback):
            self._calibrate()
            gate = self.noise_floor * GATE_MULTIPLIER
            if self.verbose:
                print("[listening]  Ctrl-C to stop")

            while not self._stop:
                try:
                    block = self.q.get(timeout=0.5)
                except queue.Empty:
                    continue

                ring.append(block)
                level = rms(block)
                hot = level > gate

                if state == "IDLE":
                    if hot:
                        # Seed the working buffer with the ring so we keep the
                        # transmission's opening samples.
                        working = list(ring)
                        silence_run = 0.0
                        sync_deadline = time.time() + SYNC_TIMEOUT_S
                        state = "RECEIVING"

                elif state == "RECEIVING":
                    working.append(block)
                    if hot:
                        silence_run = 0.0
                    else:
                        silence_run += block_seconds

                    # End the reception after enough trailing silence...
                    done = silence_run >= SILENCE_HANG_S
                    # ...or bail if it never looked like a real transmission.
                    timed_out = time.time() > sync_deadline and silence_run > 0
                    if done or timed_out:
                        buf = np.concatenate(working)
                        self._handle(buf)
                        working = []
                        silence_run = 0.0
                        state = "IDLE"

    def _handle(self, buf: np.ndarray):
        result = decode(buf)
        self.failures.record(result)
        if result.ok:
            self.on_message(result.text)
        elif self.verbose:
            print(result.line())

    def stop(self):
        self._stop = True

    @staticmethod
    def _default_print(text: str):
        stamp = time.strftime("%H:%M:%S")
        print(f"[{stamp}] {text}")


# --------------------------------------------------------------------------- #
# Push-to-listen fallback for debugging (fixed-length record, then decode).    #
# --------------------------------------------------------------------------- #
def record_and_decode(seconds=15, device=None, save_path=None):
    """Record a fixed window, optionally save it, then run the decode path."""
    import sounddevice as sd

    print(f"[recording {seconds}s]")
    audio = sd.rec(int(FS * seconds), samplerate=FS, channels=1,
                   dtype="float32", device=device)
    sd.wait()
    samples = audio[:, 0]

    if save_path:
        from audio_io import write_wav
        write_wav(save_path, samples)
        print(f"[saved] {save_path}")

    result = decode(samples)
    print(result.line())
    return result
