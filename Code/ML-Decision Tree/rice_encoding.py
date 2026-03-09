import math
import os
import time


#class that writes bits instead of full bytes
class BitWriter:

    #initialize writer with output file
    def __init__(self,f):

        #file object where bytes will be written
        self.f=f

        #temporary buffer storing bits before forming a byte
        self.buffer=0

        #number of bits currently stored in buffer
        self.nbits=0

    #write selected number of bits to stream
    def write_bits(self,value,nbits):

        while nbits>0:
            space=8-self.nbits
            take=min(space,nbits)
            shift=nbits-take
            chunk=(value>>shift)&((1<<take)-1)
            self.buffer=(self.buffer<<take)|chunk
            self.nbits+=take
            nbits-=take

            if self.nbits==8:
                self.f.write(bytes([self.buffer]))
                self.buffer=0
                self.nbits=0

    #with padding
    def flush(self):

        if self.nbits>0:
            self.buffer<<=(8-self.nbits)
            self.f.write(bytes([self.buffer]))
            self.buffer=0
            self.nbits=0


#class that reads bits from file
class BitReader:

    #initialize reader with input file
    def __init__(self,f):
        self.f=f
        self.buffer=0
        self.nbits=0

    #read one bit from stream
    def read_bit(self):
        if self.nbits==0:
            byte=self.f.read(1)
            if not byte:
                return None
            self.buffer=byte[0]
            self.nbits=8

        self.nbits-=1
        return (self.buffer>>self.nbits)&1

    #read n bits
    def read_bits(self,n):
        value=0
        for _ in range(n):
            bit=self.read_bit()
            if bit is None:
                raise EOFError("Unexpected EOF in bitstream")
            value=(value<<1)|bit
        return value


#rice encoder for fixed parameter k
def rice_encoder_fixed_k(writer,s,k):
    q=s>>k
    r=s&((1<<k)-1)

    if q>0:
        writer.write_bits((1<<q)-1,q)
    writer.write_bits(0,1)
    if k>0:
        writer.write_bits(r,k)


#decode one rice symbol
def rice_decode_symbol(reader,k):
    q=0
    while True:
        bit=reader.read_bit()
        if bit is None:
            raise EOFError("Unexpected EOF in unary code")
        if bit==0:
            break
        q+=1
    r=reader.read_bits(k) if k>0 else 0
    return (q<<k)|r


#estimate k using mean of window
def estimate_k_window_mean(window_bytes,k_max=7):
    if not window_bytes:
        return 0
    mean_value=sum(window_bytes)/len(window_bytes)
    if mean_value<=1:
        return 0
    k=int(math.log2(mean_value))
    return max(0,min(k,k_max))


#core encoder for plain RLE byte stream (no frame structure)
def _rice_encode_rle_stream_adaptive(in_file,out_file,k_estimator,window_size=4096):
    if window_size<=0 or window_size>0xFFFF:
        raise ValueError("window_size must be in range 1..65535")

    original_size=os.path.getsize(in_file)
    start_time=time.time()
    processed=0
    next_report=50000

    with open(in_file,"rb") as fin,open(out_file,"wb") as fout:
        writer=BitWriter(fout)

        #format:
        #[orig_size:8 bytes ]
        #repeat:
        # [window_len:2 bytes]
        # [k:1 byte]
        # [rice coded bytes for that window]
        fout.write(original_size.to_bytes(8,byteorder="little",signed=False))

        while True:
            window=fin.read(window_size)
            if not window:
                break

            k_window=k_estimator(window)

            writer.flush()
            fout.write(len(window).to_bytes(2,byteorder="little",signed=False))
            fout.write(bytes([k_window]))

            for b in window:
                rice_encoder_fixed_k(writer,b,k_window)

            processed+=len(window)
            if processed>=next_report:
                elapsed=time.time()-start_time
                rate=processed/elapsed if elapsed>0 else 0
                print(f"Processed {processed}/{original_size} bytes | Rate {rate:.1f} B/s")
                next_report+=50000

        writer.flush()

    print("Rice experiment encoding complete.")


def rice_encode_rle_adaptive_mean(in_file,out_file,window_size=4096):
    _rice_encode_rle_stream_adaptive(in_file,out_file,estimate_k_window_mean,window_size)


def rice_decode_rle_adaptive(in_file,out_file):
    with open(in_file,"rb") as fin,open(out_file,"wb") as fout:
        reader=BitReader(fin)
        original_size_raw=fin.read(8)
        if len(original_size_raw)!=8:
            raise ValueError("Truncated header")
        expected_size=int.from_bytes(original_size_raw,byteorder="little",signed=False)

        written=0
        start_time=time.time()
        next_report=50000

        while written<expected_size:
            reader.nbits=0
            win_len_raw=fin.read(2)
            if len(win_len_raw)!=2:
                raise ValueError("Truncated window length")
            window_len=int.from_bytes(win_len_raw,byteorder="little",signed=False)
            if window_len==0:
                raise ValueError("Invalid window length 0")

            k_raw=fin.read(1)
            if len(k_raw)!=1:
                raise ValueError("Truncated window k")
            k_window=k_raw[0]

            if written+window_len>expected_size:
                raise ValueError("Decoded bytes would exceed original size")

            for _ in range(window_len):
                s=rice_decode_symbol(reader,k_window)
                if s<0 or s>255:
                    raise ValueError("Decoded symbol out of byte range")
                fout.write(bytes([s]))
            written+=window_len

            if written>=next_report:
                elapsed=time.time()-start_time
                rate=written/elapsed if elapsed>0 else 0
                print(f"Decoded {written}/{expected_size} bytes | Rate {rate:.1f} B/s")
                next_report+=50000

        extra=fin.read(1)
        if extra:
            raise ValueError("Extra bytes found after expected stream")

    print("Rice experiment decoding complete.")
