# Frequency-Vibrations

Send short encrypted text messages between two computers using only sound. The sender encrypts the text with AES-256-GCM under a pre-shared 256-bit key, frames it, and plays it as two-tone FSK. The receiver listens, finds the preamble, demodulates, checks the frame, decrypts, and prints the text.

```
send.py:    encrypt → frame → modulate → WAV / speaker
receive.py: mic / WAV → demodulate → deframe → decrypt → print
```

The full design, interfaces and task split are in [`Encrypted Audio Text Transmission Team Task Plan.md`](Encrypted%20Audio%20Text%20Transmission%20Team%20Task%20Plan.md).

## Install

Python 3.10 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest          # all tests, including the WAV loopback; run before any hardware test
```

## Key setup

```bash
python keygen.py          # writes key.bin (32 random bytes, mode 600) and prints a fingerprint
python keygen.py --hex    # writes key.hex (64 hex characters) for pasting between terminals
```

Copy the key to the other computer by USB stick, or paste a hex key between terminals you control. Never send it over audio or a chat app, and never commit it. Both `send.py` and `receive.py` print the key fingerprint (e.g. `16e4-c703`); check that it matches on both computers. Instead of `--key`, you can set `FV_KEY_PATH=/path/to/key.bin`.

## Sending

```bash
python send.py "hello" --key key.bin --out msg.wav          # write a WAV
python send.py "hello" --key key.bin --play [--device N]    # play through the speaker
```

The sender prints the message and frame sizes, the audio length and the key fingerprint. Messages can be up to 484 UTF-8 bytes. A bad key or an oversized message prints one `error:` line and exits 1.

## Receiving

```bash
python receive.py --key key.bin [--device N]                        # live: listen continuously
python receive.py --key key.bin --record-seconds 15 [--save-recordings]   # push-to-listen
python receive.py --key key.bin --from-wav msg.wav                  # decode a WAV offline
```

- **Live mode:** the receiver measures the room noise for one second, then opens an energy gate at about 3× that level. It records until 1 s of silence or until `MAX_FRAME_SECONDS + 2` (about 43.5 s), then decodes. Ctrl-C prints a tally of successes and failures.
- **Push-to-listen** records a fixed window (default 15 s, capped at about 43.5 s), then decodes it. 15 s fits messages up to about 140 bytes; the 484-byte maximum needs about 42 s. `--save-recordings` also writes the recording to `recordings/`, so a failed attempt can be replayed with `--from-wav`.
- **Output:** each decoded message prints with a timestamp. Non-printable characters (newlines, tabs, terminal escape codes) are replaced with `�`, so a message cannot rewrite your terminal.
- **Failures** print exactly one line, never the garbled bytes:

| Line | Meaning |
| --- | --- |
| `[discarded: no signal decoded]` | No preamble found, or the recording ended before the frame did |
| `[discarded: corrupted header]` | Bad header CRC or a length outside 28..512 |
| `[discarded: failed authentication]` | Wrong key, or the message was altered in transit |

## Agreed constants (`common.py`)

| Constant | Value |
| --- | --- |
| Sample rate | 48000 Hz (switch everyone to 44100 if a device refuses 48k) |
| Bit 0 / bit 1 tones | 2000 Hz / 3000 Hz |
| Symbol duration | 10 ms (480 samples), 100 bits/s |
| Preamble | 16 alternating bits `0101…`, then sync byte `0x7E` |
| Bit / byte order | MSB first; multi-byte fields big-endian |
| Frame | length (2) + CRC-16/CCITT-FALSE of length (2, init 0xFFFF) + body |
| Body | nonce (12) + ciphertext + GCM tag (16); 28..512 bytes; length field authenticated as GCM `aad` |

The message `hi` gives a 34-byte frame, about 3 s of tones; a 100-character message takes about 11 s.

## `reference.wav`

`reference.wav` is a fixed test signal that needs no key: `write_wav("reference.wav", modulate(frame(bytes(range(32)))))`. Decoding it must give `deframe(demodulate(read_wav("reference.wav"))) == bytes(range(32))`. `tests/test_demod.py` checks that the file still matches the current `modulate`; if you change the modulator on purpose, regenerate it with:

```bash
python -c "from modem import modulate, write_wav; from framing import frame; write_wav('reference.wav', modulate(frame(bytes(range(32)))))"
```

## Troubleshooting

- **Microphone permission (macOS):** the first run asks for permission for your terminal app (Terminal, iTerm, VS Code), not for the script. If nothing is ever heard, check System Settings → Privacy & Security → Microphone.
- **Wrong audio device:** list devices with `python -c "import sounddevice; print(sounddevice.query_devices())"` and pass `--device N` to `send.py` or `receive.py`.
- **Device refuses 48 kHz:** change `SAMPLE_RATE` in `common.py` to 44100 on both computers (team decision), and regenerate `reference.wav`. Phone recordings need converting first: `ffmpeg -i in.m4a -ac 1 -ar 48000 out.wav`.
- **Volume:** keep system volume at a fixed level (50%) for test runs so results are comparable.
- **Mic processing:** turn off OS noise suppression, automatic gain and echo cancellation before over-the-air tests, and turn them back on afterwards.

## Over-the-air results

Fill in pass/fail and the failure type (`no signal`, `header`, `auth`) for each run.

| Distance | 25% volume | 50% volume | 100% volume |
| --- | --- | --- | --- |
| 0.3 m | | | |
| 1 m | | | |
| 2 m | | | |

## Safety and privacy

Read this before the first audio test. None of it is hard to follow, but the hearing and key items are easy to get wrong.

- **Hearing:** never test with headphones or earbuds. 2–3 kHz is the range human hearing is most sensitive to, so the tones sound much louder than music at the same volume. Start at 25–50% system volume, keep 100% runs short, and don't stand right in front of the speaker.
- **Speakers:** don't loop full-volume tones for minutes at a time. A single message plays for at most `MAX_FRAME_SECONDS` (about 42 s).
- **Microphone permission** goes to the terminal app (Terminal, iTerm, VS Code), not the script, so anything you run there can record afterwards. Revoke it when you're done testing (macOS: System Settings → Privacy & Security → Microphone). Turn noise suppression and automatic gain back on after testing.
- **Recordings** made with `--save-recordings` contain whatever was said in the room. They stay out of git but not off your disk: delete `recordings/` when you're done.
- **Keys:** keep `key.bin`/`key.hex` outside iCloud, Dropbox, OneDrive and other synced folders. On a Mac with iCloud "Desktop & Documents" on, the Desktop and Documents folders count. `load_key` and `keygen` warn when they detect this. Move keys by USB stick, never through a chat app, and never commit one: anything pushed stays in git history even after it's deleted.
- **Known limitation:** someone who records a transmission can play it back later and it will decode again. Replay protection is out of scope for the proof of concept.
