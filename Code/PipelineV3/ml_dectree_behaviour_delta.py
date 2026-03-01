#master frame size(each window will have a mode)
WINDOW_SIZE=32

#modes
BYPASS=0
SEQUENTIAL=1
MASTER=2

def behaviour_selector(F1, F2):
    #we got this from dec tree
    #f1 or f2=no. of zero bytes in seq or master/total bytes(256)
    if (F2<=0.42) and (F1<=0.44):
        return BYPASS
    elif F1>0.44:
        return SEQUENTIAL
    else:
        return MASTER

def compute_delta(current_frame, reference_frame): 
    #here frames are of integer values

    delta_frame=[]

    #corresponding bytes of each frame are paired in tuples for subtraction. zip function returns a list of these tuples. like [(F9,A5),(01,C8)] but not hexa, integer.
    zipped_list=zip(current_frame, reference_frame)

    for i,j in zipped_list:
        delta=(i-j)

        #0XFF in hex=11111111 in binary=255 in decimal.
        #& 0xFF exactly means % 256. we do this so that byte is between 0 to 255 (for AEC and also for contituity)
        delta_wrapped=delta & 0xFF

        delta_frame.append(delta_wrapped)
    return delta_frame

#this function assignes the delta calculation mode to a wnidow of frame(excpet first one) based on the trebds of the previous window. assumung some relational telemetry.
def frames_to_delta_ml(frames, out_bin, compute_window_features):

    # write to binary output file
    with open(out_bin, "wb") as f:

        #for first frame/window
        prev_frame=None
        master_refs=[None]*32 #this will be a list of lists/frames later
        prev_window=None
        frame_index=0
        current_mode=SEQUENTIAL 

        #we make windows of 32 frames each- check relation from behavior delta function and set delts calculating mode of all those 32 frames
        window=[]
    
        #frames is the original telemtry as hexa string. for each frame:
        for frame in frames:
            
            #convert each hexadecimal stringin the list to integer - int(str,16)
            current_frame_int=[int(i, 16) for i in frame]

            #slot is 0 to 31, resets every 32 frames. for master periodic
            slot=frame_index%32

            #add frame to window list
            window.append(frame)

            #when window is filled with 32 frames/elements
            if len(window)==WINDOW_SIZE:

                #compute features of this window by a function from FEATURE EXTRACTION code
                F1,F2=compute_window_features(window,prev_window)

                #assign delta mode to this window
                current_mode=behaviour_selector(F1, F2)

                #now for next empty window set up previous window 
                prev_window=window
                window=[]

            #for first frame/window
            if prev_frame is None:

                #no delta- raw
                #write mode as bytes list
                f.write(bytes([BYPASS]))

                #write first frame data raw as bytes (list)
                f.write(bytes(current_frame_int))

                #now for next frame
                prev_frame=current_frame_int

                #for master periodic mode- first slot is first frame/ every %32 slot is the first frame of 32 frame window- which is raw
                master_refs[slot]=current_frame_int.copy()

                frame_index+=1
                continue
            
            #for first frame of every window these statements wont be executed, also first window till 2nd last element/frame
            if current_mode==BYPASS:
                out_frame=current_frame_int

            elif current_mode==SEQUENTIAL:
                out_frame = compute_delta(current_frame_int, prev_frame)

            elif current_mode==MASTER:
                ref=master_refs[slot]

                #these statements never execute, but as redundancy- if none- sequential
                if ref is None:
                    ref=prev_frame
                out_frame=compute_delta(current_frame_int, ref)

            f.write(bytes([current_mode]))
            f.write(bytes(out_frame))
            prev_frame=current_frame_int

            #master_refs is a list of frames and that keeps building until 32 frames are filled. so whole previous window is held in memory
            master_refs[slot]=current_frame_int.copy()

            frame_index+=1
