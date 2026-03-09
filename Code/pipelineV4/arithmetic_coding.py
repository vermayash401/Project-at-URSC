import os

TOP = 0xFFFFFFFF
HALF = 0x80000000
FIRST_QTR = 0x40000000
THIRD_QTR = 0xC0000000

class BitWriter:
    def __init__(self, f):
        self.f = f
        self.buffer = 0
        self.nbits = 0

    def write_bit(self, bit):
        self.buffer = (self.buffer << 1) | (bit & 1)
        self.nbits += 1
        if self.nbits == 8:
            self.f.write(bytes([self.buffer]))
            self.buffer = 0
            self.nbits = 0

    def flush(self):
        if self.nbits > 0:
            self.buffer <<= (8 - self.nbits)
            self.f.write(bytes([self.buffer]))
            self.buffer = 0
            self.nbits = 0

class BitReader:
    def __init__(self, f):
        self.f = f
        self.buffer = 0
        self.nbits = 0

    def read_bit(self):
        if self.nbits == 0:
            b = self.f.read(1)
            if not b:
                return 0
            self.buffer = b[0]
            self.nbits = 8
        bit = (self.buffer >> 7) & 1
        self.buffer = (self.buffer << 1) & 0xFF
        self.nbits -= 1
        return bit

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

def arithmetic_encode(in_file, out_file):
    """Output format:
    [original_size: 4 bytes]
    [frequency table: 256 entries, each 4 bytes]
    [arithmetic coded bitstream]"""
    original_size = os.path.getsize(in_file)
    if original_size > 0xFFFFFFFF:
        raise ValueError("Input file is too large for 4-byte original size header")

    freq = [0] * 256
    with open(in_file, "rb") as fin:
        while True:
            chunk = fin.read(65536)
            if not chunk:
                break
            for b in chunk:
                freq[b] += 1

    cum = _build_cumulative(freq)
    total = cum[256]
    if total != original_size:
        raise ValueError("Frequency model error: total count mismatch")

    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:
        fout.write(original_size.to_bytes(4, byteorder="little", signed=False))
        for f in freq:
            fout.write(f.to_bytes(4, byteorder="little", signed=False))

        bw = BitWriter(fout)

        low = 0
        high = TOP
        pending_bits = 0
        processed = 0
        next_report = 50000

        def output_bit_plus_pending(bit):
            nonlocal pending_bits
            bw.write_bit(bit)
            while pending_bits > 0:
                bw.write_bit(1 - bit)
                pending_bits -= 1

        while True:
            chunk = fin.read(65536)
            if not chunk:
                break

            for sym in chunk:
                r = high - low + 1
                sym_low = cum[sym]
                sym_high = cum[sym + 1]
                high = low + (r * sym_high // total) - 1
                low = low + (r * sym_low // total)

                while True:
                    if high < HALF:
                        output_bit_plus_pending(0)
                    elif low >= HALF:
                        output_bit_plus_pending(1)
                        low -= HALF
                        high -= HALF
                    elif low >= FIRST_QTR and high < THIRD_QTR:
                        pending_bits += 1
                        low -= FIRST_QTR
                        high -= FIRST_QTR
                    else:
                        break

                    low = (low << 1) & TOP
                    high = ((high << 1) & TOP) | 1

                processed += 1
                if processed >= next_report:
                    print(f"Arithmetic encode progress: {processed} bytes processed")
                    next_report += 50000

        pending_bits += 1
        if low < FIRST_QTR:
            output_bit_plus_pending(0)
        else:
            output_bit_plus_pending(1)
        bw.flush()

    compressed_size = os.path.getsize(out_file)
    print("Arithmetic coding complete")
    print(f"Original size: {original_size}")
    print(f"Compressed size: {compressed_size}")


def arithmetic_decode(in_file, out_file):
    """Decode a file produced by arithmetic_encode()."""
    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:
        header = fin.read(4)
        if len(header) != 4:
            raise ValueError("Truncated arithmetic header")
        original_size = int.from_bytes(header, byteorder="little", signed=False)

        freq = [0] * 256
        for i in range(256):
            raw = fin.read(4)
            if len(raw) != 4:
                raise ValueError("Truncated frequency table")
            freq[i] = int.from_bytes(raw, byteorder="little", signed=False)

        cum = _build_cumulative(freq)
        total = cum[256]

        if original_size == 0:
            if total != 0:
                raise ValueError("Invalid arithmetic stream: non-zero model for empty input")
            return
        if total != original_size:
            raise ValueError("Invalid arithmetic stream: frequency total != original size")

        br = BitReader(fin)

        low = 0
        high = TOP
        code = 0
        for _ in range(32):
            code = ((code << 1) & TOP) | br.read_bit()

        written = 0
        next_report = 50000

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
                code = ((code << 1) & TOP) | br.read_bit()

            if written >= next_report:
                print(f"Arithmetic decode progress: {written} bytes restored")
                next_report += 50000

