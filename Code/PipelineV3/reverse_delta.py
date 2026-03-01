WINDOW_SIZE=32

BYPASS=0
SEQUENTIAL=1
MASTER=2


def reverse_delta_ml(in_bin,out_txt,compute_window_features=None) :

    #[1 byte mode][256 bytes payload]
    FRAME_SIZE=256

    with open(in_bin,"rb") as f_in, open(out_txt,"w") as f_out:

        #first frame
        prev_frame=None
        master_refs=[None]*32
        frame_index=0

        #for whole file
        while True:
            
            #read mode
            mode_byte=f_in.read(1)

            #just in case
            if not mode_byte:
                break

            current_frame_mode=mode_byte[0]

            #read frame from pointer(after mode byte)
            frame=f_in.read(FRAME_SIZE)

            #just in case
            if len(frame)<FRAME_SIZE:
                break

            current_frame=list(frame)

            #slot resests every 32 frames (0-31)
            slot=frame_index%32

            #first frame raw
            if prev_frame is None:
                reconstructed=current_frame

            else:
                if current_frame_mode==BYPASS:
                    reconstructed=current_frame

                elif current_frame_mode==SEQUENTIAL:

                    #same concept as encoder
                    reconstructed = [(i+j)&0xFF for i,j in zip(prev_frame, current_frame)]

                elif current_frame_mode==MASTER:

                    #master_refs stores 32 frames of previous window, slot corresponds frame
                    ref=master_refs[slot]
                    if ref is None:
                        ref=prev_frame

                    reconstructed=[(i+j)&0xFF for i,j in zip(ref,current_frame)]
                
                #error just incase
                else:
                    raise ValueError(f"Unknown mode byte: {current_frame_mode}")

            #int to hexa string, every frame in new line
            f_out.write(" ".join(f"{i:02X}" for i in reconstructed)+"\n")

            #for next frame
            prev_frame=reconstructed
            master_refs[slot]=reconstructed.copy()
            frame_index+=1