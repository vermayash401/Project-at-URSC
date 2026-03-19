from pathlib import Path
import shutil
import time

'''
    This code decompressess the output produced by Spacecraft_Telemetry_Compression.py
    
    Input is the compressed telemetry (.bin) file produced by said code.

    Output is an exact reconstructed telemetry txt file, without any loss.

'''
########################### Delta Encoding ##################################

#modes
BYPASS=0
SEQUENTIAL=1
MASTER=2

def reverse_delta_ml(in_bin,out_txt) :
    with open(in_bin,"rb") as f_in, open(out_txt,"w") as f_out:
        prev_frame=None
        master_refs=[None]*32
        frame_index=0

        lead_space=bool(f_in.read(1)[0])
        upper_case=bool(f_in.read(1)[0])
        FRAME_SIZE = int.from_bytes(f_in.read(4), byteorder="little", signed=False)
        while True:
            mode_byte=f_in.read(1)
            if not mode_byte:
                break

            current_frame_mode=mode_byte[0]
            frame=f_in.read(FRAME_SIZE)

            if len(frame)<FRAME_SIZE:
                break

            current_frame=list(frame)
            slot=frame_index%32

            if prev_frame is None:
                reconstructed=current_frame
            else:
                if current_frame_mode==BYPASS:
                    reconstructed=current_frame
                elif current_frame_mode==SEQUENTIAL:
                    reconstructed = [(i+j)&0xFF for i,j in zip(prev_frame, current_frame)]
                elif current_frame_mode==MASTER:
                    ref=master_refs[slot]
                    if ref is None:
                        ref=prev_frame
                    reconstructed=[(i+j)&0xFF for i,j in zip(ref,current_frame)]
                else:
                    raise ValueError(f"Unknown mode byte: {current_frame_mode}")
            if lead_space==False and upper_case==True:
                f_out.write(" ".join(f"{i:02X}" for i in reconstructed)+"\n")
            elif lead_space==True and upper_case==True:
                f_out.write(" "+" ".join(f"{i:02X}" for i in reconstructed)+"\n")
            elif lead_space==False and upper_case==False:
                f_out.write(" ".join(f"{i:02x}" for i in reconstructed)+"\n")
            elif lead_space==True and upper_case==False:
                f_out.write(" "+" ".join(f"{i:02x}" for i in reconstructed)+"\n")
            prev_frame=reconstructed
            master_refs[slot]=reconstructed.copy()
            frame_index+=1

########################### Zero Run Length Encoding #########################

#tags(headers for 2 packets)
tag_zero=0x00
tag_literal=0x01

def zero_rle_decode(in_file, out_file, zero_chunk_size=65536):
    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:

        original_size_raw=fin.read(8)

        if len(original_size_raw)!=8:
            raise ValueError("Invalid ZRLE file: truncated original-size field")
        
        expected_size=int.from_bytes(original_size_raw, byteorder="little", signed=False)

        written=0

        def write_zeros(count):
            nonlocal written
            block=b"\x00" * min(zero_chunk_size, 65536)
            remaining=count
            while remaining>0:
                take=min(remaining, len(block))
                fout.write(block[:take])
                written+=take
                remaining-=take

        while True:
            tag_raw=fin.read(1)
            if not tag_raw:
                break

            tag=tag_raw[0]
            if tag==tag_zero:
                count_raw=fin.read(4)
                if len(count_raw)!=4:
                    raise ValueError("Truncated zero-run packet")
                count=int.from_bytes(count_raw, byteorder="little", signed=False)
                if count==0:
                    raise ValueError("Invalid zero-run packet with count 0")
                if written+count>expected_size:
                    raise ValueError("Decoded output would exceed header original size")
                write_zeros(count)

            elif tag==tag_literal:
                length_raw = fin.read(2)
                if len(length_raw)!= 2:
                    raise ValueError("Truncated literal packet length")
                length=int.from_bytes(length_raw, byteorder="little", signed=False)
                if length==0:
                    raise ValueError("Invalid literal packet with length 0")
                payload=fin.read(length)
                if len(payload)!=length:
                    raise ValueError("Truncated literal packet payload")
                if written+length>expected_size:
                    raise ValueError("Decoded output would exceed header original size")
                fout.write(payload)
                written+=length
            else:
                raise ValueError(f"Invalid packet tag in ZRLE stream: 0x{tag:02X}")

        if written!=expected_size:
            raise ValueError(f"Decoded size mismatch: expected {expected_size} bytes, got {written}")

################# Entropy Coding Method- Arithmetic Coding ###################

TOP = 0xFFFFFFFF
HALF = 0x80000000
FIRST_QTR = 0x40000000
THIRD_QTR = 0xC0000000

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

def arithmetic_decode(in_file, out_file):
    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:
        outer_flags_raw = fin.read(1)
        outer_flags = outer_flags_raw[0]
        zrle_done = bool(outer_flags & 0b00000001)
    
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
    return zrle_done

################################# Pipeline ###################################

def run_chain(compressed_bin, output_txt):
    compressed_path = Path(compressed_bin)
    recovered_txt = Path(output_txt)
    recovered_txt.parent.mkdir(parents=True, exist_ok=True)
    base = recovered_txt.stem
    temp_dir = recovered_txt.parent / f".{base}_tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    try:
        recovered = temp_dir / f"{base}_recovered_rle.bin"
        recovered_delta = temp_dir / f"{base}_recovered_delta.bin"

        zrle_done=arithmetic_decode(str(compressed_path), str(recovered))

        if zrle_done==True:
            zero_rle_decode(str(recovered), str(recovered_delta))
            reverse_delta_ml(str(recovered_delta), str(recovered_txt))
        else:
            reverse_delta_ml(str(recovered),str(recovered_txt))
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

################################# Main- Editable(path) #######################

def main():


    INPUT_TELEMETRY_COMPRESSED="TEST_3_compressed_python.bin"
    OUTPUT_TELEMETRY="TEST_2_reconstructed_python.txt"

    compressed_bin = str(Path(__file__).resolve().parent.parent /INPUT_TELEMETRY_COMPRESSED)
    output_txt = str(Path(__file__).resolve().parent.parent / OUTPUT_TELEMETRY)
    run_chain(compressed_bin, output_txt)

if __name__ == "__main__":
    start=time.time()
    main()
    stop=time.time()
    print(stop-start)
