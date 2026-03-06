import os
import time
import math

#class that writes bits instead of full bytes
class BitWriter:

    #initialize writer with output file
    def __init__(self,f):

        #file object where bytes will be written
        self.f=f

        #temporary buffer storing bits before forming a byte
        self.buffer=0

        #number of bits currently stored in buffer
        self.nbits=0  # number of bits currently in buffer

    #write selected number of bits to stream
    def write_bits(self,value,nbits):

        """Write lowest nbits of value into stream."""

        #continue until all bits are written
        while nbits>0:

            #remaining free space in current byte
            space=8-self.nbits

            #number of bits to write now
            take=min(space,nbits)

            #shift value so required bits move to end
            shift=nbits-take

            #extract those bits
            chunk=(value>>shift)&((1<<take)-1)

            #append bits to buffer
            self.buffer=(self.buffer<<take)|chunk

            #increase bit count
            self.nbits+=take

            #reduce remaining bits
            nbits-=take


            #write byte if buffer full
            if self.nbits==8:

                #write byte to file
                self.f.write(bytes([self.buffer]))

                #reset buffer
                self.buffer=0

                #reset bit counter
                self.nbits=0

     #with padding
    def flush(self):

        #if buffer not empty
        if self.nbits>0:

            #shift bits to fill byte
            self.buffer<<=(8-self.nbits)

            #write padded byte
            self.f.write(bytes([self.buffer]))

            #reset buffer
            self.buffer=0

            #reset bit counter
            self.nbits=0


#rice encoder for fixed parameter k
def rice_encoder_fixed_k(writer,s,k):

    m=1<<k #as 1<<k = 1*(2**k) #left shit-adds k zeros to right of 1 -keeps 8 bits
    q=s>>k #adds k zeros to left of s-keeps 8 bits
    r=s&(m-1)

    #encode unary part
    if q>0:
        
        #unary q = 11111...qtimes then 0
        one_with_q_zeros=(1<<q)

        #generate q ones
        q_ones=one_with_q_zeros-1


        #write q ones
        writer.write_bits(q_ones,q)


    #write terminating zero
    writer.write_bits(0,1) 


    #write remainder bits
    writer.write_bits(r,k)                 


#estimate k using mean of window
def estimate_k_window_mean(window_payloads,k_max=7):

    #sum of values
    total_sum=0

    #total element count
    total_count=0

    #iterate through payloads
    for payload in window_payloads:

        #add payload sum
        total_sum+=sum(payload)

        #add payload length
        total_count+=len(payload)

    #avoid divide by zero
    if total_count==0:
        return 0

    #compute mean
    mean_value=total_sum/total_count

    #small mean uses k=0
    if mean_value<=1:
        return 0

    #estimate k from log2
    k=int(math.log2(mean_value))

    #limit k range
    return max(0,min(k,k_max))

#estimate best k using brute cost
def estimate_k_window_optimal(window_payloads,k_max=7):

    #best k found
    best_k=0

    #lowest cost found
    best_cost=float("inf")

    #try all k values
    for k in range(k_max+1):

        #reset cost
        cost=0

        #iterate payloads
        for payload in window_payloads:

            #iterate symbols
            for s in payload:

                #compute quotient
                q=s>>k

                #add rice cost
                cost+=q+1+k

        #update best k
        if cost<best_cost:

            #store best cost
            best_cost=cost

            #store best k
            best_k=k

    return best_k

#main adaptive rice encoder
def rice_encode_delta_file_adaptive_k(in_file,out_file,frame_size=256):

    #frame record size
    record_size=1+frame_size
    file_size=os.path.getsize(in_file)
    if file_size%record_size!=0:
        raise ValueError("Input file size is not an exact multiple of frame record size")

    total_frames=file_size//record_size

    with open(in_file,"rb") as fin,open(out_file,"wb") as fout:

        #create bit writer
        writer=BitWriter(fout)
        frame_count=0
        start_time=time.time()
        last_print_time=0.0
        window_payloads=[]
        window_modes=[]

        while True:

            #read record
            record=fin.read(record_size)

            #stop at EOF
            if not record:
                break

            #detect truncated frame
            if len(record)!=record_size:
                raise ValueError("Truncated frame detected")
        
            #extract mode
            mode=record[0]

            #extract payload
            payload=record[1:]

            #store window data
            window_modes.append(mode)

            #store payload
            window_payloads.append(payload)

            #process window of 32 frames
            if len(window_payloads)==32:

                #estimate optimal k
                k_window=estimate_k_window_optimal(window_payloads)

    
                writer.flush()

                #write k for window
                fout.write(bytes([k_window]))

                #encode frames
                for mode_i,payload_i in zip(window_modes,window_payloads):

        
                    writer.flush()

                    #write mode
                    fout.write(bytes([mode_i]))

                    #encode payload bytes
                    for b in payload_i:

                        #rice encode symbol
                        rice_encoder_fixed_k(writer,b,k_window)

                    #increase frame count
                    frame_count+=1
                window_payloads=[]
                window_modes=[]
            now=time.time()

            if (now-last_print_time>=0.5)or(frame_count==total_frames):
                elapsed=now-start_time
                rate=frame_count/elapsed if elapsed>0 else 0.0
                remaining=total_frames-frame_count
                eta_seconds=int(remaining/rate) if rate>0 else 0
                eta_min,eta_sec=divmod(eta_seconds,60)
                print(f"Frame {frame_count}/{total_frames} | ETA {eta_min:02d}:{eta_sec:02d}",end="\r",flush=True,)
                last_print_time=now

        #handle remaining window
        if len(window_payloads)==32:

            #estimate optimal k
            k_window=estimate_k_window_optimal(window_payloads)
            writer.flush()

            #write window k
            fout.write(bytes([k_window]))

            #encode frames
            for mode_i,payload_i in zip(window_modes,window_payloads):
    
                writer.flush()

                #write mode
                fout.write(bytes([mode_i]))

                #encode payload
                for b in payload_i:

                    #encode symbol
                    rice_encoder_fixed_k(writer,b,k_window)

                #increase frame count
                frame_count+=1

        writer.flush()

    print()
    print(f"Rice encoding complete. Frames processed: {frame_count}")

'''
k=5
frame_size=256
n=18
rice_encode_delta_file_adaptive_k(
    "original_telemetry_delta20.bin",
    "compressed_telemtery_adaptive_k20_optimal.bin",
    frame_size)'''