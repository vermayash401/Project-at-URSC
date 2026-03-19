import os
from pathlib import Path
import shutil
import time

'''
    This code assumes the telemetry file is a .txt file
    with frames of 2 digit hexadecimal (bytes) values 
    which are space separated.

    Frame Length: Does not matter, code handles all frame
    lengths as long as all frames are of same length.
    
    2 digit hexadecimal bytes: Code supports upper and lowercase
    
    Code assumes no byte is missing in a frame.
    Each frame in a new line.

    Code can handle a SPACE character before first byte of frame
    (as seen in actual telemetry file)

    Example:
    85 2b 1a 68 50 00 a7.... (or uppercase-both work)
    8f a3 39 a9 70 34 25.....

    Output: .bin file with a compressed size. Testing says compressed size 
            is about 1/10th size compared to input txt file. (sometimes more, rarely less) 
            90% size reduction. Lossless.

            This output can only be decoded/decompressed by Ground_Telemetry_Decompression.py

    '''
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

#master frame size(each window will have a mode)
WINDOW_SIZE=32

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

def frames_to_delta_ml(frames, lead_space, upper_case, FRAME_SIZE, out_bin):
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
                f.write(bytes([lead_space]))
                f.write(bytes([upper_case]))
                f.write(FRAME_SIZE.to_bytes(4, byteorder="little", signed=False))
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
max_zeros=0xFFFFFFFF #max of 4 bytes
max_literals=0xFFFF #max of 2 bytes

def zero_rle_encode(in_file, out_file, chunk_size=65536):#65536=max 2 byte value
    original_size = os.path.getsize(in_file)
    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:

        #output file structure (all binary):

        #header-(8 bytes) original size

        #stream of packets until EOF:
        #packet 0-(1 byte) tag and (4 bytes) zero count
        #Packet literal-(1 byte) tag, (2 bytes) literal length, (N bytes) literal payload

        #write header
        #8=length, byteorder= little endian = LSB(rightmost byte) of value stored first, unsigned=positive only
        fout.write(original_size.to_bytes(8, byteorder="little", signed=False))

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
                fout.write(take.to_bytes(4, byteorder="little", signed=False))
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

def _build_cumulative(freq):
    cum = [0] * 257
    running = 0
    for i in range(256):
        running += freq[i]
        cum[i + 1] = running
    return cum

def arithmetic_encode(in_file, out_file,zrle_done):
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
        outer_flags = 0
        outer_flags |= int(zrle_done) << 0
        fout.write(bytes([outer_flags]))
        fout.write(original_size.to_bytes(4, byteorder="little", signed=False))
        for f in freq:
            fout.write(f.to_bytes(4, byteorder="little", signed=False))

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

################################# Load Telemetry #############################

def load_frames_from_txt(txt_file):
    frames=[]
    with open(txt_file, "r", encoding="utf-8") as fin:
        for line in fin:
            lead_space=line.startswith(' ')
            for char in line:
                if char.isalpha():
                    upper_case=char.isupper()
                    break
            parts=line.strip().split()
            
            if not parts:
                continue
            frames.append(parts)
    
    if not frames:
        raise ValueError("Input telemetry txt has no frames")
    
    FRAME_SIZE=len(frames[0])
    return frames, lead_space, upper_case, FRAME_SIZE

################################# Pipeline ###################################

def run_chain(input_txt, output_bin):
    txt_path = Path(input_txt)
    compressed = Path(output_bin)
    compressed.parent.mkdir(parents=True, exist_ok=True)
    base = compressed.stem
    temp_dir = compressed.parent / f".{base}_tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    try:
        delta_bin = temp_dir / f"{base}_delta.bin"
        rle_bin = temp_dir / f"{base}_delta_rle.bin"

        frames, lead_space, upper_case, FRAME_SIZE = load_frames_from_txt(str(txt_path))
        frames_to_delta_ml(frames, lead_space, upper_case, FRAME_SIZE, str(delta_bin))
        deltasize=os.path.getsize(delta_bin)

        zero_rle_encode(str(delta_bin), str(rle_bin))
        zrlesize=os.path.getsize(rle_bin)
        if zrlesize>deltasize:
            entropy_input=delta_bin
            zrle_done=False
        else:
            entropy_input=rle_bin
            zrle_done=True

        arithmetic_encode(str(entropy_input), str(compressed),zrle_done)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

################################# Main- Editable(path) #######################

def main():

    INPUT_TELEMETRY="TEST_3.txt"
    OUTPUT_TELEMETRY_COMPRESSED="TEST_3_compressed_python.bin"

    input_txt = str(Path(__file__).resolve().parent.parent / INPUT_TELEMETRY)
    output_bin = str(Path(__file__).resolve().parent.parent / OUTPUT_TELEMETRY_COMPRESSED)
    run_chain(input_txt, output_bin)

if __name__ == "__main__":
    start=time.time()
    main()
    stop=time.time()
    print(stop-start)