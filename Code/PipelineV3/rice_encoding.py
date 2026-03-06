import os
import time


#class that writes bits instead of full bytes
class BitWriter:

    #initialize writer with output file
    def __init__(self, f):

        #file object where bytes will be written
        self.f = f

        #temporary buffer storing bits before forming a byte
        self.buffer=0

        #number of bits currently stored in buffer
        self.nbits=0  


    
    def write_bits(self, value, nbits):

        #continue until all bits are written
        while nbits > 0:

            #remaining free space in current byte buffer
            space=8-self.nbits

            #how many bits to write in this step
            take = min(space,nbits)

            #shift value so required bits move to end
            shift=nbits-take

            #extract only those bits
            chunk=(value>>shift)&((1<<take)-1)


            #append bits to buffer
            self.buffer=(self.buffer<<take)|chunk

            #increase buffer bit count
            self.nbits+=take

            #reduce remaining bits to write
            nbits-=take


            #if buffer reached 8 bits then write byte
            if self.nbits==8:

                #write byte to file
                self.f.write(bytes([self.buffer]))

                #reset buffer
                self.buffer=0

                #reset bit counter
                self.nbits=0


    #flush remaining bits with 0 if buffer not full
    def flush(self):


        #if buffer has partial byte
        if self.nbits>0:

            #shift remaining bits to fill byte
            self.buffer<<=(8 - self.nbits)

            #write padded byte
            self.f.write(bytes([self.buffer]))

            #reset buffer
            self.buffer = 0

            #reset bit counter
            self.nbits = 0


#rice encoder for fixed parameter k
def rice_encoder_fixed_k(writer, s, k):

    m=1<<k #as 1<<k = 1*(2**k) #left shit-adds k zeros to right of 1 -keeps 8 bits

    q=s>>k #adds k zeros to left of s-keeps 8 bits
    r=s&(m-1)
    if q>0:
        
        #unary q = 11111...qtimes then 0
        one_with_q_zeros=(1<<q)

        #generate q number of ones
        q_ones=one_with_q_zeros-1


        #write q ones (q length)
        writer.write_bits(q_ones, q)

    #write terminating zero of unary code
    writer.write_bits(0,1) 

    #write remainder using k bits
    writer.write_bits(r,k)                 

#function that reads delta file and rice compresses payload
def rice_encode_delta_file(in_file,out_file, frame_size=256,k=4,):

    #size of one frame record
    record_size=1+frame_size

    #get file size
    file_size=os.path.getsize(in_file)

    #ensure file is exact multiple of frame size
    if file_size%record_size!=0:
        raise ValueError("Input file size is not an exact multiple of frame record size")

    #calculate total frames in file
    total_frames=file_size//record_size

    #open input and output files
    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:

        #create bit writer for output
        writer=BitWriter(fout)

        #frame counter
        frame_count=0

        #record start time
        start_time=time.time()

        #last progress print time
        last_print_time=0.0

        #loop until file ends
        while True:

            #read one frame record
            record=fin.read(record_size)

            #break when end of file
            if not record:
                break

            #detect truncated frame
            if len(record)!=record_size:
                raise ValueError("Truncated frame detected")

            #extract mode byte
            mode=record[0]

            #extract payload bytes
            payload=record[1:]

            #flush bit buffer before writing raw byte
            writer.flush() 

            #write mode byte directly
            fout.write(bytes([mode]))

            #encode each payload byte
            for b in payload:
                rice_encoder_fixed_k(writer, b, k)

            frame_count+=1
            now = time.time()
            if (now - last_print_time >= 0.5) or (frame_count == total_frames):
                elapsed = now - start_time
                rate = frame_count / elapsed if elapsed > 0 else 0.0
                remaining = total_frames - frame_count
                eta_seconds = int(remaining / rate) if rate > 0 else 0
                eta_min, eta_sec = divmod(eta_seconds, 60)
                print(f"Frame {frame_count}/{total_frames} | ETA {eta_min:02d}:{eta_sec:02d}",end="\r",flush=True,)
                last_print_time = now
        writer.flush()
    print()
    print(f"Rice encoding complete. Frames processed: {frame_count}")



'''
k=5
frame_size=256
n=18
rice_encode_delta_file(
    f"original_telemetry_delta{n}.bin",
    f"rice_output_{n}_{k}.bin",
    frame_size,
    k)'''