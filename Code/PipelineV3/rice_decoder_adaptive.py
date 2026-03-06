import os
import time

#class that reads bits from file
class BitReader:

    #initialize reader with input file
    def __init__(self,f):

        #file object to read from
        self.f=f

        #buffer storing current byte
        self.buffer=0

        #number of bits remaining in buffer
        self.nbits=0

    #read one bit from stream
    def read_bit(self):

        #if buffer empty load new byte
        if self.nbits==0:

            #read next byte
            byte=self.f.read(1)

            #return none if eof
            if not byte:
                return None

            #store byte in buffer
            self.buffer=byte[0]

            #reset bit counter
            self.nbits=8

        #reduce available bits
        self.nbits-=1

        #return next bit
        return (self.buffer>>self.nbits)&1

    #read multiple bits and combine into value
    def read_bits(self,n):

        #initialize result
        value=0

        #loop n times
        for _ in range(n):

            #read one bit
            bit=self.read_bit()

            #detect unexpected end
            if bit is None:
                raise EOFError("Unexpected EOF in bitstream")

            #shift and append bit
            value=(value<<1)|bit

        return value

#decode one rice symbol
def rice_decode_symbol(reader,k):

    #unary quotient
    q=0

    #read unary bits
    while True:

        #read next bit
        bit=reader.read_bit()

        #detect unexpected eof
        if bit is None:
            raise EOFError("Unexpected EOF in unary code")

        #stop when zero appears
        if bit==0:
            break

        #count number of ones
        q+=1

    #read remainder
    r=reader.read_bits(k)

    #reconstruct value
    return (q<<k)|r

#main adaptive rice decoder
def rice_decode_file_adaptive_k(in_file,out_file,frame_size=256,window_size=32):


    #open input and output files
    with open(in_file,"rb") as fin,open(out_file,"wb") as fout:

        #create bit reader
        reader=BitReader(fin)

        #frame counter
        frame_count=0
        start_time=time.time()

        #read until eof
        while True:

            #ensure byte alignment before reading window header
            reader.nbits=0

            #read k for window
            k_byte=fin.read(1)

            #break at eof
            if not k_byte:
                break

            #extract window k
            k_window=k_byte[0]

            #decode frames in this window
            for i in range(window_size):

                #align reader before mode
                reader.nbits=0

                #read mode byte
                mode_byte=fin.read(1)

                #stop if eof
                if not mode_byte:
                    break

                #extract mode
                mode=mode_byte[0]

                #store payload
                payload=[]

                #decode payload symbols
                for i in range(frame_size):

                    #decode rice symbol
                    s=rice_decode_symbol(reader,k_window)

                    #store value
                    payload.append(s)

                #write mode byte
                fout.write(bytes([mode]))

                #write payload
                fout.write(bytes(payload))
                frame_count+=1
                if frame_count%1000==0:
                    elapsed=time.time()-start_time
                    rate=frame_count/elapsed if elapsed>0 else 0
                    print(f"Decoded frames: {frame_count} | Rate {rate:.1f} fps",end="\r",flush=True)
    print()
    print("Decoding complete. Frames:",frame_count)