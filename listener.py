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
  * Every reception is capped at MAX_FRAME_SECONDS + 2 so constant room noise
    cannot keep the gate open and grow the buffer forever.
  * Failures are counted and printed as one clean line, never garbled bytes.
"""

import collections
import os
import queue
import time

import numpy as np

from common import MAX_FRAME_SECONDS, PREAMBLE_BITS, SAMPLE_RATE, SYMBOL_SECONDS
from decoder import DISCARD_LINES, decode

BLOCKSIZE = 1024
RING_SECONDS = 2.0
MAX_RECORD_SECONDS = MAX_FRAME_SECONDS + 2

# Listener tuning; local to the receiver, so not part of the shared contract.
GATE_MULTIPLIER = 3.0       # gate threshold = noise floor * this
GATE_MIN_RMS = 1e-3         # floor for the threshold in a very quiet room
SILENCE_HANG_S = 1.0        # quiet time that ends a reception
SYNC_TIMEOUT_S = 3.0        # SYNC gives up if the gate closes this soon...
SYNC_MIN_HOT_S = (len(PREAMBLE_BITS) + 8) * SYMBOL_SECONDS  # ...with less than a preamble of signal


def rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(block ** 2))) if len(block) else 0.0


def timestamped(text: str) -> str:
    return f"[{time.strftime('%H:%M:%S')}] {text}"


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
        for reason in DISCARD_LINES:
            parts.append(f"{reason}={self.counts[reason]}")
        return "  ".join(parts)


class Listener:
    """Owns the input stream, the state machine, and the decode handoff."""

    def __init__(self, key: bytes, device=None, on_message=None, verbose=True):
        self.key = key
        self.device = device
        self.on_message = on_message or (lambda text: print(timestamped(text)))
        self.verbose = verbose
        self.q: "queue.Queue[np.ndarray]" = queue.Queue()
        self.failures = FailureLog()
        self.noise_floor = GATE_MIN_RMS
        self._stop = False

        self.state = "IDLE"
        self._ring = collections.deque(maxlen=int(RING_SECONDS * SAMPLE_RATE / BLOCKSIZE) + 1)
        self._working: list[np.ndarray] = []
        self._samples = 0       # samples in the working buffer
        self._hot_s = 0.0       # seconds above the gate since it opened
        self._silence_s = 0.0   # current run of trailing quiet

    @property
    def gate(self) -> float:
        return self.noise_floor * GATE_MULTIPLIER

    # --- audio callback: copy + queue only --------------------------------- #
    def _callback(self, indata, frames, time_info, status):
        if status and self.verbose:
            # Overflow here means dropped audio — worth knowing during OTA tests.
            print(f"[audio status] {status}")
        self.q.put(indata[:, 0].copy())

    # --- noise-floor calibration ------------------------------------------- #
    def calibrate(self, blocks) -> None:
        """Set the noise floor from blocks of room audio (the first second)."""
        blocks = list(blocks)
        if blocks:
            self.noise_floor = max(rms(np.concatenate(blocks)), GATE_MIN_RMS)
        if self.verbose:
            print(f"[calibrated] noise floor rms={self.noise_floor:.5f} gate={self.gate:.5f}")

    def _calibration_blocks(self, seconds=1.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                yield self.q.get(timeout=0.5)
            except queue.Empty:
                return

    # --- state machine ----------------------------------------------------- #
    def feed(self, block: np.ndarray) -> None:
        """Advance the state machine by one block of samples."""
        block_s = len(block) / SAMPLE_RATE
        hot = rms(block) > self.gate
        self._ring.append(block)

        if self.state == "IDLE":
            if hot:
                # Seed the working buffer with the ring so we keep the
                # transmission's opening samples.
                self._working = list(self._ring)
                self._samples = sum(len(b) for b in self._working)
                self._hot_s, self._silence_s = block_s, 0.0
                self.state = "SYNC"
            return

        self._working.append(block)
        self._samples += len(block)
        if hot:
            self._hot_s += block_s
            self._silence_s = 0.0
        else:
            self._silence_s += block_s

        if self.state == "SYNC":
            if self._hot_s >= SYNC_MIN_HOT_S:
                self.state = "RECEIVING"
            elif self._silence_s >= SILENCE_HANG_S or self._samples / SAMPLE_RATE > SYNC_TIMEOUT_S:
                self._reset()  # a click or a burst of noise, too short to be a preamble
                return

        if self.state == "RECEIVING":
            done = self._silence_s >= SILENCE_HANG_S
            capped = self._samples >= MAX_RECORD_SECONDS * SAMPLE_RATE
            if done or capped:
                buf = np.concatenate(self._working)
                self._reset()
                self._handle(buf)

    def _reset(self) -> None:
        self._working = []
        self._samples = 0
        self._hot_s = self._silence_s = 0.0
        self.state = "IDLE"

    def _handle(self, buf: np.ndarray):
        result = decode(buf, self.key)
        self.failures.record(result)
        if result.ok:
            self.on_message(result.text)
        elif self.verbose:
            print(result.line())

    # --- main loop --------------------------------------------------------- #
    def run(self):
        import sounddevice as sd

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=BLOCKSIZE, device=self.device,
                            callback=self._callback):
            self.calibrate(self._calibration_blocks())
            if self.verbose:
                print("[listening]  Ctrl-C to stop")

            while not self._stop:
                try:
                    block = self.q.get(timeout=0.5)
                except queue.Empty:
                    continue
                self.feed(block)

    def stop(self):
        self._stop = True


# --------------------------------------------------------------------------- #
# Push-to-listen fallback for debugging (fixed-length record, then decode).    #
# --------------------------------------------------------------------------- #
def record_and_decode(key: bytes, seconds=15, device=None, save_dir=None):
    """Record a fixed window (capped at MAX_RECORD_SECONDS), optionally save it, then decode."""
    import sounddevice as sd

    seconds = min(seconds, MAX_RECORD_SECONDS)
    print(f"[recording {seconds:g}s]")
    audio = sd.rec(int(SAMPLE_RATE * seconds), samplerate=SAMPLE_RATE, channels=1,
                   dtype="float32", device=device)
    sd.wait()
    samples = audio[:, 0]

    if save_dir:
        from modem import write_wav
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, time.strftime("%Y%m%d-%H%M%S.wav"))
        write_wav(path, samples)
        print(f"[saved] {path}  (contains room audio; delete after testing)")

    result = decode(samples, key)
    print(timestamped(result.text) if result.ok else result.line())
    return result
