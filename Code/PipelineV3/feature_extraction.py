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