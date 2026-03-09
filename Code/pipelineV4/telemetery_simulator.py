import random

#32 frames every 16 sec=2 frame/s
FRAMES_PER_MINUTE=120
FRAME_SIZE_BYTES=256
#days=5
#max_changes=64 #bytes of out 256


def build_frame(header,frame_id,payload):
    # bytes 0 to 4 constant per 32-frame block
    frame=list(header)              
       
    # byte 5=frame id 00 to 1F (0 to 32) - 0 to fill extra space, 2 is max length, x is hexadecimal
    frame.append(f"{frame_id:02X}")  

    # bytes 6 to 255
    frame.extend(payload)         
    return frame

def random_payload(rng,n=250):
    #rng=random number generator=random.Random(seed)
    #list of random bytes (250)
    return [f"{rng.getrandbits(8):02X}" for i in range(n)]


def mutate_payload(prev_payload,rng,max_changes=6):
    #no change
    if max_changes<=0:
        return prev_payload.copy()
    
    #new frame initial state
    out=prev_payload.copy()

    #random number of changes (smaller than max, more than 1)
    changes=rng.randint(1,max_changes) 

    #changes number of times
    for i in range(changes):

        #random position in payload
        pos=rng.randrange(len(out))

        #change byte as 2 digit hexa string randomly
        out[pos]=f"{rng.getrandbits(8):02X}"
    return out

#sequentially related telemetry
def generate_seq_frames(days=1,max_changes=6,frame_mode=[0.33,0.33,0.33],seed=None):

    #this is random number generator rng everywhere
    rng=random.Random(seed)

    #total frames as per number of days
    total_frames=int(days*24*60*FRAMES_PER_MINUTE)

    frames=[]

    #for progress print
    last_progress_len=0

    #split equally into 3 modes
    same_frames=total_frames//3
    low_var_frames=total_frames//3
    random_frames=total_frames-same_frames-low_var_frames

    #same and low variance first frames
    same_payload_global=random_payload(rng,250)
    low_var_prev_payload=random_payload(rng,250)

    for i in range(total_frames):
        
        #remiander for frame id to repeat every 32 frames(0 to 31)
        frame_id=i%32 

        #first frame header
        if frame_id==0:
            header=[f"{rng.getrandbits(8):02X}" for i in range(5)]

        #all 3 modes equally
        if  frame_mode==[0.33,0.33,0.33]:
            if i<same_frames:
                mode="same"
            elif i<same_frames + low_var_frames:
                mode="low_var"
            else:
                mode="random"
        
        #2/3rd low variance, rest random
        elif frame_mode==[0,0.66,0.33]:
            if i<same_frames:
                mode="low_var"
            elif i<same_frames+low_var_frames:
                mode="low_var"
            else:
                mode="random"

        #all low variance
        elif frame_mode==[0,10,0]:
            mode="low_var"
        
        #all random
        elif frame_mode==[0,0,10]:
            mode="random"

        #now for modes
        if mode=="same":
            payload=same_payload_global
        elif mode=="low_var":
            low_var_prev_payload=mutate_payload(low_var_prev_payload, rng, max_changes)
            payload=low_var_prev_payload
        else:
            payload=random_payload(rng, 250)

        frames.append(build_frame(header, frame_id, payload))

        #progress print every 10000 frames 
        if (i+1)%10000==0 or (i+1)==total_frames:
            progress_text=f"{total_frames-(i+1)} frames left"
            last_progress_len=len(progress_text)
            print(f"\r{progress_text}", end="", flush=True)
    if last_progress_len>0:
        print("\r"+(" " * last_progress_len)+"\r", end="",flush=True)

    return frames


def generate_master_correlated_frames(days=1, max_changes=6,frame_mode=[0.33,0.33,0.33], seed=None):
    rng=random.Random(seed)
    total_frames=int(days*24*60*FRAMES_PER_MINUTE)
    frames=[]
    last_progress_len=0

    same_frames=total_frames//3
    low_var_frames_master=total_frames//3
    random_frames=total_frames-same_frames-low_var_frames_master

    same_payload_global=random_payload(rng, 250)

    #list of 32 random payloads
    master_index_states=[random_payload(rng, 250) for i in range(32)]

    for i in range(total_frames):
        frame_id=i%32
        if frame_id==0:
            header=[f"{rng.getrandbits(8):02X}" for i in range(5)]

        if  frame_mode==[0.33,0.33,0.33]:
            if i<same_frames:
                mode="same"
            elif i<same_frames+low_var_frames_master:
                mode="low_var_master"
            else:
                mode="random"
        
        elif frame_mode==[0,0.66,0.33]:
            if i<same_frames:
                mode="low_var_master"
            elif i<same_frames+low_var_frames_master:
                mode="low_var_master"
            else:
                mode="random"

        elif frame_mode==[0,10,0]:
            mode="low_var_master"
        
        elif frame_mode==[0,0,10]:
            mode="random"

        if mode=="same":
            payload=same_payload_global

        elif mode=="low_var_master":

            #first frame of every MF: when it enters a new mf
            if frame_id==0:

                #32 times, so a whole new list of lists, ie master frame(payload) is created, slotwise changed from previous, at the start only
                for j in range(32):
                    master_index_states[j]=mutate_payload(master_index_states[j], rng, max_changes)

            #but each frame is appended, with every loop iteration +1
            payload=master_index_states[frame_id]

        else:  
            payload=random_payload(rng, 250)

        frames.append(build_frame(header, frame_id, payload))

        #progress print
        if (i + 1) % 10000 == 0 or (i + 1) == total_frames:
            progress_text = f"{total_frames - (i + 1)} frames left"
            last_progress_len = len(progress_text)
            print(f"\r{progress_text}", end="", flush=True)

    if last_progress_len > 0:
        print("\r" + (" " * last_progress_len) + "\r", end="", flush=True)

    return frames


def save_frames_to_txt(frames, path="spacecraft_frames.txt"):
    with open(path, "w", encoding="utf-8") as f:
        for frame in frames:
            f.write(" ".join(frame) + "\n")

def generate_telemetry(days, max_changes,frame_mode,mode="Sequential", txt_output="spacecraft_framesX.txt"): #, bin_output= "spacecraft_framesX_delta.bin",):
    print("------------------------------------------------------------------------")
    if mode == "Master Correlated":
        frames = generate_master_correlated_frames(days, max_changes,frame_mode)
    else:
        frames = generate_seq_frames(days, max_changes,frame_mode)
    save_frames_to_txt(frames, path=txt_output)
    print("TELEMETRY GENERATED: ", len(frames), "frames")
    print("------------------------------------------------------------------------")
    return frames
    

def mixed_telemetry (days=0.05, max_changes=[1, 2, 4, 8, 16, 32, 64],txt_output="spacecraft_framesX.txt"):

    l=len(max_changes)
    each_regime_data_duration_in_days=days/(2*(l+1))
    frames_same = generate_seq_frames(each_regime_data_duration_in_days,0,[0,10,0])
    frames_random = generate_seq_frames(each_regime_data_duration_in_days,0,[0,0,10])# here max changes doesnt matter
    frames_related=[]
    for i in max_changes:
        frames_master = generate_master_correlated_frames(each_regime_data_duration_in_days,i,[0,10,0])
        frames_seq = generate_seq_frames(each_regime_data_duration_in_days,i,[0,10,0])
        frames_related.extend(frames_master)
        frames_related.extend(frames_seq)
    frames=frames_same+frames_related+frames_random
    save_frames_to_txt(frames, path=txt_output)
    return frames
