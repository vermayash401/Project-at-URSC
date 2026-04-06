import io
import sys
import time
from pathlib import Path


BYPASS = 0
SEQUENTIAL = 1
MASTER = 2

BATCH_RAW_DELTA = 0
BATCH_RAW_ZRLE = 1
BATCH_ARITHMETIC = 2

TAG_ZERO = 0x00
TAG_LITERAL = 0x01

TOP = 0xFFFFFFFF
HALF = 0x80000000
FIRST_QTR = 0x40000000
THIRD_QTR = 0xC0000000

FRAME_SIZE = 256
FRAMES_PER_MF = 32
MF_PER_BATCH = 4
TOTAL_FRAMES = FRAMES_PER_MF * MF_PER_BATCH
RAW_SIZE = TOTAL_FRAMES * FRAME_SIZE


def reverse_delta_ml(data):
    frames = []
    prev_frame = None
    master_refs = [None] * FRAMES_PER_MF
    frame_index = 0
    idx = 0

    while idx < len(data):
        mode = data[idx]
        idx += 1

        frame = data[idx:idx + FRAME_SIZE]
        if len(frame) != FRAME_SIZE:
            raise ValueError("Truncated delta frame payload")
        idx += FRAME_SIZE

        current_frame = list(frame)
        slot = frame_index % FRAMES_PER_MF

        if prev_frame is None:
            reconstructed = current_frame
        elif mode == BYPASS:
            reconstructed = current_frame
        elif mode == SEQUENTIAL:
            reconstructed = [(a + b) & 0xFF for a, b in zip(prev_frame, current_frame)]
        elif mode == MASTER:
            ref = master_refs[slot]
            if ref is None:
                ref = prev_frame
            reconstructed = [(a + b) & 0xFF for a, b in zip(ref, current_frame)]
        else:
            raise ValueError(f"Unknown mode byte: {mode}")

        frames.append(bytearray(reconstructed))
        prev_frame = reconstructed
        master_refs[slot] = reconstructed.copy()
        frame_index += 1

    return frames


def zero_rle_decode(data):
    if len(data) < 2:
        raise ValueError("Invalid ZRLE payload: missing original-size field")

    expected_size = data[0] | (data[1] << 8)
    idx = 2
    out = bytearray()

    while idx < len(data):
        tag = data[idx]
        idx += 1

        if idx + 2 > len(data):
            raise ValueError("Truncated ZRLE packet length")

        count = data[idx] | (data[idx + 1] << 8)
        idx += 2

        if count == 0:
            raise ValueError("Invalid ZRLE packet with zero length")

        if tag == TAG_ZERO:
            out.extend(b"\x00" * count)
        elif tag == TAG_LITERAL:
            if idx + count > len(data):
                raise ValueError("Truncated ZRLE literal payload")
            out.extend(data[idx:idx + count])
            idx += count
        else:
            raise ValueError(f"Invalid ZRLE tag: 0x{tag:02X}")

        if len(out) > expected_size:
            raise ValueError("ZRLE decode exceeded expected size")

    if len(out) != expected_size:
        raise ValueError(f"ZRLE size mismatch: expected {expected_size}, got {len(out)}")

    return out


class BitReader:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.buffer = 0
        self.nbits = 0

    def read_bit(self):
        if self.nbits == 0:
            raw = self.stream.read(1)
            if not raw:
                return None
            self.buffer = raw[0]
            self.nbits = 8

        bit = (self.buffer >> 7) & 1
        self.buffer = (self.buffer << 1) & 0xFF
        self.nbits -= 1
        return bit


def build_cumulative(freq):
    cum = [0] * 257
    running = 0
    for i in range(256):
        running += freq[i]
        cum[i + 1] = running
    return cum


def find_symbol(cum, value):
    lo = 0
    hi = 256
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if cum[mid] <= value:
            lo = mid
        else:
            hi = mid
    return lo


def arithmetic_decode(payload):
    if len(payload) < 1 + 2 + (256 * 2):
        raise ValueError("Truncated arithmetic payload")

    zrle_done = bool(payload[0] & 0x01)
    original_size = payload[1] | (payload[2] << 8)

    freq = []
    idx = 3
    for _ in range(256):
        freq.append(payload[idx] | (payload[idx + 1] << 8))
        idx += 2

    cum = build_cumulative(freq)
    total = cum[256]

    if total != original_size:
        raise ValueError("Invalid arithmetic payload: frequency total mismatch")

    br = BitReader(payload[idx:])
    code = 0
    for _ in range(32):
        bit = br.read_bit()
        if bit is None:
            raise ValueError("Truncated arithmetic bitstream")
        code = ((code << 1) & TOP) | bit

    low = 0
    high = TOP
    out = bytearray()

    while len(out) < original_size:
        r = high - low + 1
        value = ((code - low + 1) * total - 1) // r
        sym = find_symbol(cum, value)
        out.append(sym)

        sym_low = cum[sym]
        sym_high = cum[sym + 1]
        high = low + (r * sym_high // total) - 1
        low = low + (r * sym_low // total)

        while True:
            if high < HALF:
                pass
            elif low >= HALF:
                low -= HALF
                high -= HALF
                code -= HALF
            elif low >= FIRST_QTR and high < THIRD_QTR:
                low -= FIRST_QTR
                high -= FIRST_QTR
                code -= FIRST_QTR
            else:
                break

            low = (low << 1) & TOP
            high = ((high << 1) & TOP) | 1
            bit = br.read_bit()
            if bit is None:
                bit = 0
            code = ((code << 1) & TOP) | bit

    return out, zrle_done


def decode_payload(batch_type, payload):
    if batch_type == BATCH_RAW_DELTA:
        delta_bytes = payload
    elif batch_type == BATCH_RAW_ZRLE:
        delta_bytes = zero_rle_decode(payload)
    elif batch_type == BATCH_ARITHMETIC:
        recovered, zrle_done = arithmetic_decode(payload)
        delta_bytes = zero_rle_decode(recovered) if zrle_done else recovered
    else:
        raise ValueError(f"Unknown batch type marker: {batch_type}")

    return reverse_delta_ml(delta_bytes)


def wait_until_complete(path, poll_interval=0.5, stable_rounds=3):
    stable = 0
    last_size = -1

    while stable < stable_rounds:
        try:
            current_size = path.stat().st_size
        except FileNotFoundError:
            stable = 0
            last_size = -1
            time.sleep(poll_interval)
            continue

        if current_size > 0 and current_size == last_size:
            stable += 1
        else:
            stable = 0
            last_size = current_size

        time.sleep(poll_interval)


def decode_file(path):
    data = path.read_bytes()
    if len(data) < 3:
        raise ValueError("Invalid batch file")

    batch_type = data[0]
    payload_size = data[1] | (data[2] << 8)
    payload = data[3:]

    if len(payload) != payload_size:
        raise ValueError(f"Payload size mismatch: header={payload_size}, actual={len(payload)}")

    frames = decode_payload(batch_type, payload)
    reconstructed_size = len(frames) * FRAME_SIZE
    ratio = RAW_SIZE / len(data)

    print("\n=== NASA cFS Telemetrty batch detected ===")
    print("File:", path)
    if batch_type==2:
        print("Type:", "Arithmetic")
    elif batch_type==0:
        print("Type:", "Raw")
    else:
            print("Type:", "ZRLE")
    print("Compressed Telemetry batch size:", len(data))
    #print("Payload size:", payload_size)
    print("Frames reconstructed:", len(frames),"=",len(frames)/32,"Master Frames")
    print("Raw size:", RAW_SIZE)
    print("Reconstructed size:", reconstructed_size)
    print("Compression ratio:", round(ratio, 3))

    if reconstructed_size == RAW_SIZE:
        print("Status: Reconstruction SUCCESS")
    else:
        print("Status: Incomplete reconstruction")

    out_path = path.with_suffix(".decoded.txt")
    with out_path.open("w", encoding="utf-8") as f:
        for frame in frames:
            f.write(" ".join(f"{b:02X}" for b in frame) + "\n")

    print("Decoded frames saved to:", out_path)

    batch_id = path.stem.split("_")[-1]
    raw_frame_path = Path("/tmp") / f"comp_batch_{batch_id}.raw.txt"

    if raw_frame_path.exists() and frames:
        raw_first = raw_frame_path.read_text(encoding="utf-8").strip()
        decoded_first = " ".join(f"{b:02X}" for b in frames[0])

        if raw_first == decoded_first:
            print("First frame check: MATCH")
        else:
            print("First frame check: MISMATCH")
            print("Raw frame file:", raw_frame_path)
    else:
        print("First frame check: Raw frame file not found")


def main():
    watch_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    pattern = sys.argv[2] if len(sys.argv) > 2 else "received_batch_*.bin"

    print(f"Listening in {watch_dir} for {pattern}\nfor NASA cFS Telemetry batches")

    processed = set()
    while True:
        for path in sorted(watch_dir.glob(pattern)):
            if path in processed:
                continue

            try:
                wait_until_complete(path)
                decode_file(path)
                processed.add(path)
            except Exception as exc:
                print(f"Failed to decode {path}: {exc}")
                processed.add(path)

        time.sleep(1.0)


if __name__ == "__main__":
    main()
