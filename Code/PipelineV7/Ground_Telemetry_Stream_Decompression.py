import shutil
import time
from pathlib import Path

"""
Decompresses the streamed output produced by
Spacecraft_telemetry_stream_compressor.py.

The compressed file is just a concatenation of arithmetic-coded batches.
Each batch expands to either:
1. delta stream directly
2. ZRLE stream, then delta stream

The whole file is reconstructed in one run.
"""

########################### Delta Encoding ##################################

BYPASS = 0
SEQUENTIAL = 1
MASTER = 2
FRAME_SIZE_BYTES = 256

def reverse_delta_ml(in_bin, out_txt, append=False):
    mode = "a" if append else "w"
    with open(in_bin, "rb") as f_in, open(out_txt, mode, encoding="utf-8") as f_out:
        prev_frame = None
        master_refs = [None] * 32
        frame_index = 0

        while True:
            mode_byte = f_in.read(1)
            if not mode_byte:
                break

            current_frame_mode = mode_byte[0]
            frame = f_in.read(FRAME_SIZE_BYTES)
            if len(frame) != FRAME_SIZE_BYTES:
                raise ValueError("Truncated delta frame payload")

            current_frame = list(frame)
            slot = frame_index % 32

            if prev_frame is None:
                reconstructed = current_frame
            else:
                if current_frame_mode == BYPASS:
                    reconstructed = current_frame
                elif current_frame_mode == SEQUENTIAL:
                    reconstructed = [(i + j) & 0xFF for i, j in zip(prev_frame, current_frame)]
                elif current_frame_mode == MASTER:
                    ref = master_refs[slot]
                    if ref is None:
                        ref = prev_frame
                    reconstructed = [(i + j) & 0xFF for i, j in zip(ref, current_frame)]
                else:
                    raise ValueError(f"Unknown mode byte: {current_frame_mode}")

            f_out.write(" ".join(f"{i:02X}" for i in reconstructed) + "\n")

            prev_frame = reconstructed
            master_refs[slot] = reconstructed.copy()
            frame_index += 1


########################### Zero Run Length Encoding #########################

tag_zero = 0x00
tag_literal = 0x01


def zero_rle_decode(in_file, out_file, zero_chunk_size=65536):
    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:
        original_size_raw = fin.read(2)
        if len(original_size_raw) != 2:
            raise ValueError("Invalid ZRLE file: truncated original-size field")

        expected_size = int.from_bytes(original_size_raw, byteorder="little", signed=False)
        written = 0

        def write_zeros(count):
            nonlocal written
            block = b"\x00" * min(zero_chunk_size, 65536)
            remaining = count
            while remaining > 0:
                take = min(remaining, len(block))
                fout.write(block[:take])
                written += take
                remaining -= take

        while True:
            tag_raw = fin.read(1)
            if not tag_raw:
                break

            tag = tag_raw[0]
            if tag == tag_zero:
                count_raw = fin.read(2)
                if len(count_raw) != 2:
                    raise ValueError("Truncated zero-run packet")
                count = int.from_bytes(count_raw, byteorder="little", signed=False)
                if count == 0:
                    raise ValueError("Invalid zero-run packet with count 0")
                if written + count > expected_size:
                    raise ValueError("Decoded output would exceed header original size")
                write_zeros(count)
            elif tag == tag_literal:
                length_raw = fin.read(2)
                if len(length_raw) != 2:
                    raise ValueError("Truncated literal packet length")
                length = int.from_bytes(length_raw, byteorder="little", signed=False)
                if length == 0:
                    raise ValueError("Invalid literal packet with length 0")
                payload = fin.read(length)
                if len(payload) != length:
                    raise ValueError("Truncated literal packet payload")
                if written + length > expected_size:
                    raise ValueError("Decoded output would exceed header original size")
                fout.write(payload)
                written += length
            else:
                raise ValueError(f"Invalid packet tag in ZRLE stream: 0x{tag:02X}")

        if written != expected_size:
            raise ValueError(f"Decoded size mismatch: expected {expected_size} bytes, got {written}")


################# Entropy Coding Method- Arithmetic Coding ###################

TOP = 0xFFFFFFFF
HALF = 0x80000000
FIRST_QTR = 0x40000000
THIRD_QTR = 0xC0000000

BATCH_RAW_DELTA = 0
BATCH_RAW_ZRLE = 1
BATCH_ARITHMETIC = 2


class BitReader:
    def __init__(self, f):
        self.f = f
        self.buffer = 0
        self.nbits = 0

    def read_bit(self):
        if self.nbits == 0:
            b = self.f.read(1)
            if not b:
                return None
            self.buffer = b[0]
            self.nbits = 8
        bit = (self.buffer >> 7) & 1
        self.buffer = (self.buffer << 1) & 0xFF
        self.nbits -= 1
        return bit

    def read_bits(self, n):
        value = 0
        for _ in range(n):
            bit = self.read_bit()
            if bit is None:
                raise EOFError("Unexpected EOF in bitstream")
            value = (value << 1) | bit
        return value

    def align_to_byte(self):
        self.buffer = 0
        self.nbits = 0


def _build_cumulative(freq):
    cum = [0] * 257
    running = 0
    for i in range(256):
        running += freq[i]
        cum[i + 1] = running
    return cum


def _find_symbol(cum, value):
    lo = 0
    hi = 256
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if cum[mid] <= value:
            lo = mid
        else:
            hi = mid
    return lo

def arithmetic_decode_stream(fin, out_file):
    start_pos = fin.tell()
    outer_flags_raw = fin.read(1)
    if not outer_flags_raw:
        return None
    if len(outer_flags_raw) != 1:
        raise ValueError("Truncated arithmetic flags")

    outer_flags = outer_flags_raw[0]
    zrle_done = bool(outer_flags & 0b00000001)

    header = fin.read(2)
    if len(header) != 2:
        raise ValueError("Truncated arithmetic header")
    original_size = int.from_bytes(header, byteorder="little", signed=False)

    freq = [0] * 256
    for i in range(256):
        raw = fin.read(2)
        if len(raw) != 2:
            raise ValueError("Truncated frequency table")
        freq[i] = int.from_bytes(raw, byteorder="little", signed=False)

    cum = _build_cumulative(freq)
    total = cum[256]

    if original_size == 0:
        if total != 0:
            raise ValueError("Invalid arithmetic stream: non-zero model for empty input")
        Path(out_file).write_bytes(b"")
        return zrle_done
    if total != original_size:
        raise ValueError("Invalid arithmetic stream: frequency total != original size")

    br = BitReader(fin)
    code = 0
    for _ in range(32):
        bit = br.read_bit()
        if bit is None:
            raise ValueError("Truncated arithmetic bitstream")
        code = ((code << 1) & TOP) | bit

    low = 0
    high = TOP
    written = 0

    with open(out_file, "wb") as fout:
        while written < original_size:
            r = high - low + 1
            value = ((code - low + 1) * total - 1) // r
            sym = _find_symbol(cum, value)

            fout.write(bytes([sym]))
            written += 1

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

    br.align_to_byte()
    if fin.tell() == start_pos:
        raise ValueError("Arithmetic decoder did not consume input")
    return zrle_done


def decode_batch_payload(batch_payload, batch_type, recovered, recovered_delta, recovered_txt):
    if batch_type == BATCH_ARITHMETIC:
        with open(batch_payload, "rb") as fin:
            zrle_done = arithmetic_decode_stream(fin, str(recovered))
        if zrle_done is None:
            raise ValueError("Missing arithmetic batch payload")
        if zrle_done:
            zero_rle_decode(str(recovered), str(recovered_delta))
            reverse_delta_ml(str(recovered_delta), str(recovered_txt), append=True)
        else:
            reverse_delta_ml(str(recovered), str(recovered_txt), append=True)
    elif batch_type == BATCH_RAW_ZRLE:
        zero_rle_decode(str(batch_payload), str(recovered_delta))
        reverse_delta_ml(str(recovered_delta), str(recovered_txt), append=True)
    elif batch_type == BATCH_RAW_DELTA:
        reverse_delta_ml(str(batch_payload), str(recovered_txt), append=True)
    else:
        raise ValueError(f"Unknown batch type marker: {batch_type}")


################################# Pipeline ###################################

def run_stream_chain(compressed_bin, output_txt):
    compressed_path = Path(compressed_bin)
    recovered_txt = Path(output_txt)
    recovered_txt.parent.mkdir(parents=True, exist_ok=True)
    base = recovered_txt.stem
    temp_dir = recovered_txt.parent / f".{base}_tmp"

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    try:
        if recovered_txt.exists():
            recovered_txt.unlink()

        batch_index = 0
        with open(compressed_path, "rb") as fin:
            while True:
                recovered = temp_dir / f"batch_{batch_index + 1:06d}_recovered.bin"
                recovered_delta = temp_dir / f"batch_{batch_index + 1:06d}_delta.bin"
                batch_type_raw = fin.read(1)
                if not batch_type_raw:
                    break
                if len(batch_type_raw) != 1:
                    raise ValueError("Truncated batch type marker")

                batch_type = batch_type_raw[0]
                payload_length_raw = fin.read(2)
                if len(payload_length_raw) != 2:
                    raise ValueError("Truncated batch payload length")
                payload_length = int.from_bytes(payload_length_raw, byteorder="little", signed=False)
                if payload_length == 0:
                    raise ValueError("Invalid empty batch payload")

                batch_payload = fin.read(payload_length)
                if len(batch_payload) != payload_length:
                    raise ValueError("Truncated batch payload")

                batch_payload_file = temp_dir / f"batch_{batch_index + 1:06d}_payload.bin"
                batch_payload_file.write_bytes(batch_payload)
                decode_batch_payload(batch_payload_file, batch_type, recovered, recovered_delta, recovered_txt)

                batch_index += 1

        print(f"Recovered {batch_index} arithmetic batches into {recovered_txt}")
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


################################# Main- Editable(path) #######################

def main():
    input_telemetry_compressed = "telemetry_stream_compressed5.bin"
    output_telemetry = "telemetry_stream_reconstructed5.txt"

    compressed_bin = str(Path(__file__).resolve().parent.parent / input_telemetry_compressed)
    output_txt = str(Path(__file__).resolve().parent.parent / output_telemetry)
    run_stream_chain(compressed_bin, output_txt)


if __name__ == "__main__":
    start = time.time()
    main()
    stop = time.time()
    print(stop - start)
