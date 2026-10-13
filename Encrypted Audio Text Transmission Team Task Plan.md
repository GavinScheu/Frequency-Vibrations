# Encrypted Audio Text Transmission: Team Task Plan

Oct 13, 2026 · @j

## Overview

Four people can build the proof of concept in parallel if they agree on interfaces first and meet at a loopback test (WAV file, no microphone) before going over the air.

Two computers exchange short text messages using only audio. The sender encrypts the text with AES-256-GCM under a pre-shared 256-bit key, encodes the result as FSK tones, and plays it. The receiver listens, detects the preamble, demodulates, decrypts, and displays the text.

- **Person 1:** crypto, framing, key handling, sender CLI
- **Person 2:** transmitter audio (modulation, WAV, playback)
- **Person 3:** receiver demodulation, tested offline from WAV files
- **Person 4:** live listener, integration, testing, README

## Step 0: Agree on interfaces (all four, about 30 min)

Put these in one shared `common.py` before anyone splits off, so the pieces fit together later.

Function signatures:

- `encrypt(plaintext: str, key: bytes) -> bytes` returns nonce + ciphertext + tag; `decrypt(blob: bytes, key: bytes) -> str` reverses it
- `frame(body: bytes) -> bytes` returns length + header CRC + body; `deframe(data: bytes) -> bytes` checks the CRC and returns the body
- `modulate(frame: bytes) -> np.ndarray` prepends the preamble and sync byte and returns float samples; `demodulate(samples: np.ndarray) -> bytes` returns the frame bytes

Starting constants (put them in `common.py`, change them only by team agreement):

| Constant | Starting value | Why |
| --- | --- | --- |
| Sample rate | 48000 Hz | Default on most sound cards; if a device refuses it, use 44100 everywhere |
| Bit 0 tone | 2000 Hz | Mid-range, reproduced well by laptop speakers and mics |
| Bit 1 tone | 3000 Hz | 1000 Hz from the other tone, so the two are easy to tell apart |
| Symbol duration | 10 ms (480 samples) | 100 bits/s; both tones fit a whole number of cycles per symbol (20 and 30), so they do not leak into each other's detector |
| Preamble | 16 alternating bits (0101...) then sync byte `0x7E` | Alternation gives symbol timing; the sync byte marks where the length field starts |
| Bit and byte order | Most significant bit first; length is big-endian | `np.unpackbits` and `np.packbits` already work this way |
| Max body | 512 bytes | Rejects a garbage length field |

Frame layout after the preamble and sync byte: length (2 bytes, size of the body) + header CRC-16 (2 bytes) + body (12-byte nonce + ciphertext + 16-byte GCM tag).

At 100 bits/s, a 100-character message (about 130 bytes with overhead) takes about 11 seconds. Treat that as the baseline and raise the rate only after everything works, by shortening the symbol to 5 ms.

Suggested files: `common.py` (constants and the signatures above), `crypto.py`, `framing.py`, `modem.py` (modulate and demodulate), `send.py`, `receive.py`, `tests/`.

## Jacob: Crypto, framing, key handling

- [ ] Generate and load the 256-bit pre-shared key
  - Keygen script: `key = os.urandom(32)`, written to `key.bin` (or hex in a text file); restrict permissions with `chmod 600`
  - Loader: read the path from a `--key` argument or an environment variable, and raise an error unless the result is exactly 32 bytes
  - Copy the key to the second computer by USB stick or a one-time paste; never send it over audio, and keep it out of git (`.gitignore`)
- [ ] Implement `encrypt` and `decrypt` with AES-256-GCM
  - Use `from cryptography.hazmat.primitives.ciphers.aead import AESGCM`
  - Encrypt: `nonce = os.urandom(12)`, then `AESGCM(key).encrypt(nonce, plaintext.encode('utf-8'), aad)`; the library returns ciphertext with the 16-byte tag appended; return `nonce + that`
  - Pass the 2-byte length field as `aad` so GCM also authenticates the header
  - Decrypt: split off the first 12 bytes as the nonce; catch `InvalidTag` and raise your own `DecryptionError` so the receiver can print a clean message
  - Never reuse a nonce with the same key; a fresh random nonce per message is enough at this scale
- [ ] Implement `frame` and `deframe`
  - `frame`: `header = struct.pack('>H', len(body))`, `crc = binascii.crc_hqx(header, 0)`, return `header + struct.pack('>H', crc) + body`
  - `deframe`: check the CRC first and reject the frame if it fails or if the length exceeds the 512-byte cap, then return exactly `length` bytes of body
  - The preamble and sync byte are added by `modulate`, not here
- [ ] Write unit tests (pytest) in `tests/test_crypto.py` and `tests/test_framing.py`
  - Round trip for short, empty, and non-ASCII messages (for example an accented character or an emoji)
  - Wrong key raises `DecryptionError`; flipping one bit anywhere in the blob raises `DecryptionError`
  - Oversized message is rejected on the send side; corrupted header CRC is rejected by `deframe`
  - Two encryptions of the same message give different output (different nonces)
- [ ] Write the sender CLI `send.py`
  - Usage: `python send.py "hello" --key key.bin --out msg.wav --play` (`--out` writes the WAV, `--play` also plays it)
  - Pipeline: `encrypt`, then `frame`, then `modulate`, then `write_wav` and `play` from Person 2
  - Until Person 2's code lands, stub `modulate` to return silence so the CLI can be tested

## Julia: Transmitter audio

- [ ] Implement `modulate` (FSK)
  - Bits: `bits = np.unpackbits(np.frombuffer(frame, dtype=np.uint8))` (most significant bit first); prepend the preamble bits and the sync byte
  - Per-sample frequency: `freq = np.repeat(np.where(bits == 1, F1, F0), SAMPLES_PER_SYMBOL)`
  - Build the waveform with continuous phase so there are no clicks at symbol boundaries: `phase = 2 * np.pi * np.cumsum(freq) / FS`, then `signal = np.sin(phase)`
  - Apply a 5 ms fade in and fade out, and add about 0.5 s of silence before and after
  - Scale to a peak of about 0.8 and return `float32` so playback and WAV writing both work
- [ ] Write WAV output
  - Convert with `(signal * 32767).astype(np.int16)`
  - Use the stdlib `wave` module: `setnchannels(1)`, `setsampwidth(2)`, `setframerate(FS)`, then `writeframes(data.tobytes())`
  - Check the file opens in an audio player and sounds like two alternating tones
- [ ] Play through the speaker
  - `sounddevice.play(signal, FS)` followed by `sounddevice.wait()`
  - List devices with `sounddevice.query_devices()` and add an optional `--device` argument
  - Keep system volume at a fixed level (for example 50%) and note it in the README so test runs are comparable
- [ ] Tune tone frequencies and symbol rate with Person 3
  - Keep each tone at a whole number of cycles per symbol so the detector stays clean
  - Try the pairs 2000/3000 Hz and 1500/2500 Hz, and symbol lengths of 20, 10, and 5 ms
  - Avoid tones below about 500 Hz (small speakers roll off) and above about 6 kHz (microphones and compression roll off)
- [ ] Verify the audio visually
  - Plot a spectrogram with `matplotlib.pyplot.specgram(signal, Fs=FS)` and confirm two clear horizontal bands at the chosen frequencies, switching in the pattern of the preamble
  - Save one reference WAV (for example `reference.wav` with a known message) for Person 3 to test against

## Person 3: Receiver demodulation (offline)

- [ ] Implement tone detection per symbol window
  - Precompute two reference vectors: `ref0 = np.exp(-2j*np.pi*F0*n/FS)` and `ref1` likewise, where `n = np.arange(SAMPLES_PER_SYMBOL)`
  - For a window `w`, compare `abs(np.dot(w, ref1))` with `abs(np.dot(w, ref0))`; the larger is the bit (this is the same as Goertzel for one frequency, and simpler to write)
  - Unit-test it on clean tones from `modulate`: every window must decode correctly
- [ ] Implement preamble detection and symbol-timing alignment
  - Slide a window across the recording in steps of about one tenth of a symbol (48 samples); at each offset decode the 24 preamble and sync bits and count how many match
  - Take the offset with the best match (a perfect or near-perfect score); that offset is the start of the symbol grid
  - Reject the recording if no offset scores above a threshold (for example 22 of 24 bits)
  - Optionally refine by searching one-sample steps within a tenth of a symbol around the best offset
- [ ] Implement `demodulate`
  - After the sync byte, decode 32 bits (length and header CRC), verify the CRC, then decode exactly `length * 8` more bits
  - Convert bits to bytes with `np.packbits` and return the frame bytes for Person 1's `deframe`
  - Return a clear error (no preamble found, bad header CRC, recording ended early) rather than garbage
- [ ] Test entirely offline with WAV files
  - Decode Person 2's `reference.wav` first, then random messages of varying length
  - Stress tests: add Gaussian noise at 20, 10, and 0 dB signal-to-noise ratio; scale volume to 50%, 10%, and 5%; prepend random leading silence; play the WAV through a speaker and record it with a phone to get realistic distortion
- [ ] Measure and report bit error rate
  - Script: send known random bytes, demodulate, and compare bit by bit
  - Run across symbol lengths (20, 10, 5 ms) and noise levels, and record the results in a small table
  - Report the fastest symbol rate with zero errors at realistic noise; the team uses it as the baseline

## Person 4: Live listener, integration, testing

- [ ] Build the continuous capture loop
  - `sounddevice.InputStream(samplerate=FS, channels=1, dtype='float32', blocksize=1024, callback=cb)`
  - The callback only copies and queues: `q.put(indata[:, 0].copy())`; log the `status` argument, since overflow warnings mean dropped audio
  - A processing loop pulls from the queue; keep a ring buffer of the last 2 seconds (`collections.deque` of blocks) so the start of a transmission is not lost when the gate opens late
- [ ] Build the state machine (IDLE, SYNC, RECEIVING)
  - Energy gate: compute `rms = np.sqrt(np.mean(block**2))`; measure the room noise floor for the first second and set the threshold to about 3 times that (with a small minimum)
  - IDLE to SYNC when the gate opens; copy the ring buffer into the working buffer
  - SYNC to RECEIVING when Person 3's preamble check succeeds on the working buffer; SYNC back to IDLE after a 3 s timeout
  - RECEIVING ends when the decoded length has been reached; then hand the buffer to `demodulate`
  - Simplest first version: record from gate-open until 1 s of silence, then call `demodulate` on the whole buffer; move to true streaming only if there is time
  - Reject any length field above the 512-byte cap
- [ ] Handle failures cleanly
  - If `deframe` rejects the header or `decrypt` raises `DecryptionError`, print one line such as `[discarded: failed authentication]`, never the garbled bytes, and return to IDLE
  - Log how often each failure type happens during the over-the-air tests
- [ ] Build the receiver CLI `receive.py`
  - Usage: `python receive.py --key key.bin [--device N]`; prints each decoded message with a timestamp
  - Pipeline: capture, `demodulate`, `deframe`, `decrypt`, print
- [ ] Build a push-to-listen fallback for debugging
  - `audio = sounddevice.rec(int(FS * SECONDS), samplerate=FS, channels=1); sounddevice.wait()`, then the same decode path; add `--record-seconds 15`
  - Optionally save every recording to a WAV file so a failed over-the-air attempt can be replayed offline
- [ ] Own the end-to-end tests
  - Loopback script: `send.py` writes a WAV, the decoder reads it, assert the plaintext matches; run it automatically before any hardware test
  - Over-the-air matrix: distance 0.3 m, 1 m, 2 m by speaker volume 25%, 50%, 100%; record pass or fail and failure type in a table
  - Turn off operating-system microphone processing (noise suppression, automatic gain, echo cancellation) before testing
- [ ] Write the README
  - Install: `pip install numpy sounddevice cryptography` (plus `matplotlib` and `pytest` for the optional tools)
  - Key setup, run commands for sender and receiver, and the agreed constants
  - Troubleshooting: microphone permission prompts, wrong default audio device, devices that refuse 48 kHz (switch everyone to 44100), and the test results table

## Milestones

| Milestone | Goal | Who |
| --- | --- | --- |
| M0 | Interfaces and constants agreed | All |
| M1 | Crypto and framing tested; WAV generated; offline decode of WAV works | Persons 1, 2, 3 |
| M2 | Loopback pass: send CLI to WAV to decoder to correct plaintext, no mic | All |
| M3 | Live capture and state machine working (needs M2) | Person 4 |
| M4 | Over the air between two computers | All |
| M5 | Tuning, demo prep, README | All |

## Dependencies and scope

Persons 2 and 3 should swap test WAVs in the first hour, because a disagreement on bit order, symbol timing, or preamble is cheapest to find early. Person 4 can start the capture loop and state machine immediately against a stub `demodulate`, and needs the real one only at M3.

Out of scope for the proof of concept:

- Key exchange or public-key crypto
- Replay protection and sender authentication beyond the shared key
- Error-correcting codes (Reed-Solomon is the stretch goal if over-the-air decoding is flaky)
- Noisy environments, multiple simultaneous senders, and messages beyond a few hundred bytes
