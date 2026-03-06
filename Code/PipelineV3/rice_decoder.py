import os
import time


#class that reads bits from a file
class BitReader:

    #initialize reader with input file
    def __init__(self,f):

        #file object to read bytes from
        self.f=f

        #buffer storing current byte
        self.buffer=0

        #number of bits remaining in buffer
        self.nbits=0


    #read one bit from stream
    def read_bit(self):

        #if no bits left in buffer
        if self.nbits==0:

            #read next byte
            byte=self.f.read(1)

            #if end of file reached
            if not byte:
                return None

            #store byte in buffer
            self.buffer=byte[0]

            #reset bit counter
            self.nbits=8


        #reduce available bits
        self.nbits-=1

        #return next bit from buffer
        return (self.buffer>>self.nbits)&1


    #read multiple bits and combine to value
    def read_bits(self,n):

        #initialize output value
        value=0

        #loop n times
        for i in range(n):

            #read single bit
            bit=self.read_bit()

            #detect unexpected end of file
            if bit is None:
                raise EOFError("Unexpected EOF in bitstream")

            #shift and append bit
            value=(value<<1)|bit

        return value


#decode one rice coded symbol
def rice_decode_symbol(reader,k):

    #read unary quotient q
    q=0

    #read bits until zero encountered
    while True:

        #read next bit
        bit=reader.read_bit()

        #detect unexpected end
        if bit is None:
            raise EOFError("Unexpected EOF in unary code")

        #stop when zero appears
        if bit==0:
            break

        #count number of ones
        q+=1


    #read remainder bits
    r=reader.read_bits(k)

    #reconstruct original value
    return (q<<k)|r


#decode full rice encoded file
def rice_decode_file(in_file,out_file,frame_size=256,k=4):

    #get input file size
    file_size=os.path.getsize(in_file)


    #open input and output files
    with open(in_file,"rb") as fin,open(out_file,"wb") as fout:

        #create bit reader
        reader=BitReader(fin)
        frame_count=0
        start_time=time.time()

        #loop until file ends
        while True:

            #align reader to next byte
            reader.nbits=0

            #read mode byte
            mode_byte=fin.read(1)

            #break if end of file
            if not mode_byte:
                break

            #extract mode value
            mode=mode_byte[0]


            #store decoded payload
            payload=[]

            #decode each byte in payload
            for i in range(frame_size):

                #decode rice symbol
                s=rice_decode_symbol(reader,k)

                #store decoded value
                payload.append(s)

            #write mode byte
            fout.write(bytes([mode]))

            #write decoded payload
            fout.write(bytes(payload))
            frame_count+=1

            if frame_count%1000==0:
                elapsed=time.time()-start_time
                rate=frame_count/elapsed if elapsed>0 else 0
                print(
                    f"Decoded frames: {frame_count} | Rate {rate:.1f} fps",end="\r",flush=True,)
    print()
    print("Decoding complete. Frames:",frame_count)