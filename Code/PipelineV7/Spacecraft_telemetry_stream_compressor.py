import os
import random
import time
from pathlib import Path
import shutil

"""
Generates telemetry in a streaming manner and compresses it in batches.

The generator only produces two telemetry styles:
1. Sequentially related frames
2. Master-frame-related frames

Frames are generated continuously for the hardcoded number of days.
Every `MASTER_FRAMES_PER_BATCH` master frames (default 2, so 64 frames),
the batch is passed through the full compression pipeline and appended to
the output file immediately as one standalone arithmetic-coded block.
"""

########################### Telemetry Generator ##############################

FRAME_SIZE_BYTES = 256
MASTER_FRAMES_PER_BATCH = 2

FRAMES_PER_MINUTE = 120
PAYLOAD_BYTES = FRAME_SIZE_BYTES - 6
FRAMES_PER_MASTER_FRAME = 32

def build_frame(header, frame_id, payload):
    # bytes 0 to 4 constant per 32-frame block
    frame=list(header)              
       
    # byte 5=frame id 00 to 1F (0 to 32) - 0 to fill extra space, 2 is max length, x is hexadecimal
    frame.append(f"{frame_id:02X}")  

    # bytes 6 to 255
    frame.extend(payload)         
    return frame

def random_payload(rng, payload_bytes=PAYLOAD_BYTES):
    return [f"{rng.getrandbits(8):02X}" for _ in range(payload_bytes)]


def mutate_payload(prev_payload, rng, max_changes=6):
    if max_changes <= 0:
        return prev_payload.copy()

    out = prev_payload.copy()
    changes = rng.randint(1, max_changes)

    for _ in range(changes):
        pos = rng.randrange(len(out))
        out[pos] = f"{rng.getrandbits(8):02X}"
    return out

def total_frames_for_days(days):
    return int(days * 24 * 60 * FRAMES_PER_MINUTE)


def generate_streaming_batches(days=1, max_changes=6, master_frames_per_batch=MASTER_FRAMES_PER_BATCH, seed=None):
    rng = random.Random(seed)
    total_frames = total_frames_for_days(days)
    batch_size_frames = FRAMES_PER_MASTER_FRAME * master_frames_per_batch

    sequential_payload = random_payload(rng, PAYLOAD_BYTES)
    master_index_states = [random_payload(rng, PAYLOAD_BYTES) for _ in range(FRAMES_PER_MASTER_FRAME)]
    batch = []
    header = None
    telemetry_mode = "sequential"

    for frame_number in range(total_frames):
        frame_id = frame_number % FRAMES_PER_MASTER_FRAME
        if frame_id == 0:
            header = [f"{rng.getrandbits(8):02X}" for _ in range(5)]
            telemetry_mode = rng.choice(("sequential", "master"))

        if telemetry_mode == "sequential":
            sequential_payload = mutate_payload(sequential_payload, rng, max_changes)
            payload = sequential_payload
        else:
            if frame_id == 0:
                for slot in range(FRAMES_PER_MASTER_FRAME):
                    master_index_states[slot] = mutate_payload(master_index_states[slot], rng, max_changes)
            payload = master_index_states[frame_id]

        batch.append(build_frame(header, frame_id, payload))

        if len(batch) == batch_size_frames:
            yield batch
            batch = []

    if batch:
        yield batch


def append_frames_to_txt(frames, txt_path):
    with open(txt_path, "a", encoding="utf-8") as fout:
        for frame in frames:
            fout.write(" ".join(frame) + "\n")


########################### Feature Extraction ##############################

def compute_window_features(current_window,prev_window):
        #F1 = sequential_zero_ratio
        #F2 = master_zero_ratio

    W=len(current_window)

    #convert each hexa str in each frame of window to int (list of lists)
    current_window_int=[[int(i,16) for i in frame] for frame in current_window]

    if prev_window is not None:
        prev_window_int=[[int(i, 16) for i in frame] for frame in prev_window]
    
    #for first window -else
    else:
        prev_window_int=None

    seq_zero_count=0
    seq_total=0

    #for 32 frames we will have 31 comparisions:
    for k in range(1,W):
        prev_frame=current_window_int[k-1]
        current_frame=current_window_int[k]

        #corresponding bytes of each frame are paired in tuples for subtraction. zip function returns a list of these tuples. like [(F9,A5),(01,C8)] but not hexa, integer.
        for i,j in zip(current_frame, prev_frame):

            #subtract correspoding bytes and wrap in 256 bytes. like %256
            delta=(i-j)&0xFF

            if delta==0:
                
                #increase counter for every zero byte
                seq_zero_count+=1

            #increase counter for every byte in frame(256)
            seq_total+=1

    #just incase telemetry is corrupt
    if seq_total==0:
        F1=0
    
    else:
        F1=seq_zero_count/seq_total

    #for first window only
    if prev_window_int is None:
        F2=0
    else:
        master_zero_count=0
        master_total=0

        #for 2 windows of 32 frames each, we will have 32 comparisions
        for k in range(W):
            current_frame=current_window_int[k]
            prev_frame=prev_window_int[k]

            for i, j in zip(current_frame, prev_frame):
                delta = (i-j)&0xFF
                if delta==0:
                    master_zero_count+=1
                master_total+=1
        if master_total==0:
            F2=0
        else:
            F2=master_zero_count/master_total

    return F1,F2

########################### Delta Encoding ##################################

# master frame size (each window will have a mode)
WINDOW_SIZE = FRAMES_PER_MASTER_FRAME

#modes
BYPASS=0
SEQUENTIAL=1
MASTER=2

def behaviour_selector(F1, F2):
    if (F2<=0.42) and (F1<=0.43):
        return BYPASS
    elif F1>0.43:
        return SEQUENTIAL
    else:
        return MASTER

def compute_delta(current_frame, reference_frame):
    delta_frame=[]
    zipped_list=zip(current_frame, reference_frame)
    for i,j in zipped_list:
        delta=(i-j)
        delta_wrapped=delta & 0xFF
        delta_frame.append(delta_wrapped)
    return delta_frame

def frames_to_delta_ml(frames, out_bin):
    with open(out_bin, "wb") as f:
        prev_frame=None
        master_refs=[None]*32
        prev_window=None
        frame_index=0
        current_mode=SEQUENTIAL
        window=[]

        for frame in frames:
            current_frame_int=[int(i, 16) for i in frame]
            slot=frame_index%32
            window.append(frame)

            if len(window)==WINDOW_SIZE:
                F1,F2=compute_window_features(window,prev_window)
                current_mode=behaviour_selector(F1, F2)
                prev_window=window
                window = []

            if prev_frame is None:
                f.write(bytes([BYPASS]))
                f.write(bytes(current_frame_int))
                prev_frame=current_frame_int
                master_refs[slot]=current_frame_int.copy()
                frame_index+=1
                continue

            if current_mode==BYPASS:
                out_frame=current_frame_int
            elif current_mode==SEQUENTIAL:
                out_frame = compute_delta(current_frame_int, prev_frame)
            elif current_mode==MASTER:
                ref=master_refs[slot]
                if ref is None:
                    ref=prev_frame
                out_frame=compute_delta(current_frame_int, ref)

            f.write(bytes([current_mode]))
            f.write(bytes(out_frame))
            prev_frame=current_frame_int
            master_refs[slot]=current_frame_int.copy()
            frame_index+=1

########################### Zero Run Length Encoding #########################

#tags(headers for 2 packets)
tag_zero=0x00
tag_literal=0x01

#maximum run of zeros stored in one packet.
max_zeros=0xFFFF
max_literals=0xFFFF #max of 2 bytes

def zero_rle_encode(in_file, out_file, chunk_size=65536):#65536=max 2 byte value
    original_size = os.path.getsize(in_file)
    if original_size > 0xFFFF:
        raise ValueError("ZRLE input is too large for 2-byte V7 header")
    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:

        #output file structure (all binary):

        #header-(2 bytes) original size

        #stream of packets until EOF:
        #packet 0-(1 byte) tag and (2 bytes) zero count
        #Packet literal-(1 byte) tag, (2 bytes) literal length, (N bytes) literal payload

        #write header
        fout.write(original_size.to_bytes(2, byteorder="little", signed=False))

        zero_run=0

        #mutable array of bytes
        literal_buf=bytearray()

        #write all literals stroed in buffer with header, length, and literal as a packet
        def flush_literal():
            nonlocal literal_buf
            while literal_buf:
                take=min(len(literal_buf), max_literals)
                fout.write(bytes([tag_literal]))
                fout.write(take.to_bytes(2, byteorder="little", signed=False))
                fout.write(literal_buf[:take])
                del literal_buf[:take]

        #write count of zeros stored in buffer with header, length as packet
        def flush_zero_run():
            nonlocal zero_run
            while zero_run > 0:
                take=min(zero_run, max_zeros)
                fout.write(bytes([tag_zero]))
                fout.write(take.to_bytes(2, byteorder="little", signed=False))
                zero_run-=take

        #main logic
        while True:
            #read these many bytes
            chunk=fin.read(chunk_size)
            if not chunk:
                break
            for b in chunk:
                #when zero encountered
                if b==0:
                    if literal_buf:
                        flush_literal()
                    zero_run+=1
                    if zero_run==max_zeros:
                        flush_zero_run()
                else:
                    if zero_run:
                        flush_zero_run()
                    literal_buf.append(b)
                    if len(literal_buf)==max_literals:
                        flush_literal()
        #EOF
        if zero_run:
            flush_zero_run()
        if literal_buf:
            flush_literal()

################# Entropy Coding Method- Arithmetic Coding ###################

TOP = 0xFFFFFFFF
HALF = 0x80000000
FIRST_QTR = 0x40000000
THIRD_QTR = 0xC0000000

BATCH_RAW_DELTA = 0
BATCH_RAW_ZRLE = 1
BATCH_ARITHMETIC = 2


class BitWriter:
    def __init__(self, f):
        self.f = f
        self.buffer = 0
        self.nbits = 0

    def write_bit(self, bit):
        self.write_bits(bit & 1, 1)

    def write_bits(self, value, nbits):
        while nbits > 0:
            space = 8 - self.nbits
            take = min(space, nbits)
            shift = nbits - take
            chunk = (value >> shift) & ((1 << take) - 1)
            self.buffer = (self.buffer << take) | chunk
            self.nbits += take
            nbits -= take
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

def _build_cumulative(freq):
    cum = [0] * 257
    running = 0
    for i in range(256):
        running += freq[i]
        cum[i + 1] = running
    return cum

def arithmetic_encode(in_file, out_file, zrle_done):
    original_size = os.path.getsize(in_file)
    if original_size > 0xFFFF:
        raise ValueError("Input file is too large for 2-byte V7 arithmetic header")

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
        outer_flags = 0
        outer_flags |= int(zrle_done) << 0
        fout.write(bytes([outer_flags]))
        fout.write(original_size.to_bytes(2, byteorder="little", signed=False))
        for f in freq:
            if f > 0xFFFF:
                raise ValueError("Frequency exceeds 2-byte V7 arithmetic limit")
            fout.write(f.to_bytes(2, byteorder="little", signed=False))

        bw = BitWriter(fout)

        low = 0
        high = TOP
        pending_bits = 0

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

        pending_bits += 1
        if low < FIRST_QTR:
            output_bit_plus_pending(0)
        else:
            output_bit_plus_pending(1)
        bw.flush()

################################# Pipeline ###################################

def compress_frames_batch(frames, temp_dir, batch_index):
    if not frames:
        return b""

    delta_bin = temp_dir / f"batch_{batch_index:06d}_delta.bin"
    rle_bin = temp_dir / f"batch_{batch_index:06d}_delta_rle.bin"
    compressed_bin = temp_dir / f"batch_{batch_index:06d}_compressed.bin"

    frames_to_delta_ml(frames, str(delta_bin))
    delta_size = os.path.getsize(delta_bin)

    zero_rle_encode(str(delta_bin), str(rle_bin))
    zrle_size = os.path.getsize(rle_bin)
    if zrle_size > delta_size:
        entropy_input = delta_bin
        zrle_done = False
        batch_type_without_arithmetic = BATCH_RAW_DELTA
    else:
        entropy_input = rle_bin
        zrle_done = True
        batch_type_without_arithmetic = BATCH_RAW_ZRLE

    arithmetic_encode(str(entropy_input), str(compressed_bin), zrle_done)
    arithmetic_chunk = compressed_bin.read_bytes()
    entropy_chunk = entropy_input.read_bytes()

    if len(arithmetic_chunk) < len(entropy_chunk):
        payload = arithmetic_chunk
        batch_type = BATCH_ARITHMETIC
    else:
        payload = entropy_chunk
        batch_type = batch_type_without_arithmetic

    if len(payload) > 0xFFFF:
        raise ValueError("Batch payload exceeds 2-byte stream length limit")
    return bytes([batch_type]) + len(payload).to_bytes(2, byteorder="little", signed=False) + payload


def append_compressed_batch(output_handle, batch_payload):
    output_handle.write(batch_payload)


def run_streaming_chain(
    days,
    output_bin,
    txt_output,
    max_changes=6,
    master_frames_per_batch=MASTER_FRAMES_PER_BATCH,
    seed=None,
):
    total_frames = total_frames_for_days(days)
    compressed = Path(output_bin)
    telemetry_txt = Path(txt_output)
    compressed.parent.mkdir(parents=True, exist_ok=True)
    telemetry_txt.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = compressed.parent / f".{compressed.stem}_tmp"

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    try:
        processed_frames = 0
        telemetry_txt.write_text("", encoding="utf-8")
        with open(compressed, "wb") as fout:
            for batch_index, frames in enumerate(
                generate_streaming_batches(days, max_changes, master_frames_per_batch, seed),
                start=1,
            ):
                append_frames_to_txt(frames, telemetry_txt)
                batch_payload = compress_frames_batch(frames, temp_dir, batch_index)
                append_compressed_batch(fout, batch_payload)
                processed_frames += len(frames)
                raw_size = len(frames) * FRAME_SIZE_BYTES
                stored_size = len(batch_payload)
                compression_ratio = raw_size / stored_size if stored_size else 0
                batch_type = batch_payload[0]
                if batch_type == BATCH_RAW_DELTA:
                    stored_as = "delta"
                elif batch_type == BATCH_RAW_ZRLE:
                    stored_as = "zrle"
                else:
                    stored_as = "arithmetic"
                print(
                    f"Batch {batch_index}: "
                    f"stored_as={stored_as}, "
                    f"raw={raw_size} bytes, compressed={stored_size} bytes, "
                    f"CR={compression_ratio:.3f}, total={processed_frames}/{total_frames} frames",
                    flush=True,
                )

        txt_size = telemetry_txt.stat().st_size if telemetry_txt.exists() else 0
        compressed_size = compressed.stat().st_size if compressed.exists() else 0
        print(f"Finished writing {processed_frames} frames to {compressed}")
        print(f"Telemetry txt size={txt_size} bytes, compressed bin size={compressed_size} bytes")
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


################################# Main- Editable(path) #######################

def main():
    output_bin = Path(__file__).resolve().parent.parent / "telemetry_stream_compressed5.bin"
    output_txt = Path(__file__).resolve().parent.parent / "telemetry_stream_generated5.txt"
    days = 0.02
    master_frames_per_batch = 4
    max_changes = 128
    seed = None
    run_streaming_chain(
        days,
        str(output_bin),
        str(output_txt),
        max_changes=max_changes,
        master_frames_per_batch=master_frames_per_batch,
        seed=seed,
    )

if __name__ == "__main__":
    start=time.time()
    main()
    stop=time.time()
    print(stop-start)
