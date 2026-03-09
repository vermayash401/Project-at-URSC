#master frame size(each window will have a mode)
WINDOW_SIZE=32

#modes
BYPASS=0
SEQUENTIAL=1
MASTER=2


def behaviour_selector(F1, F2):
    if (F2<=0.42) and (F1<=0.43):
        return BYPASS
    elif F1>0.43:
        return SEQUENTIAL
    else:
        return MASTER


def compute_delta(current_frame, reference_frame):
    delta_frame=[]
    zipped_list=zip(current_frame, reference_frame)
    for i,j in zipped_list:
        delta=(i-j)
        delta_wrapped=delta & 0xFF
        delta_frame.append(delta_wrapped)
    return delta_frame


def frames_to_delta_ml(frames, out_bin, compute_window_features):
    with open(out_bin, "wb") as f:
        prev_frame=None
        master_refs=[None]*32
        prev_window=None
        frame_index=0
        current_mode=SEQUENTIAL
        window=[]

        for frame in frames:
            current_frame_int=[int(i, 16) for i in frame]
            slot=frame_index%32
            window.append(frame)

            if len(window)==WINDOW_SIZE:
                F1,F2=compute_window_features(window,prev_window)
                current_mode=behaviour_selector(F1, F2)
                prev_window=window
                window = []

            if prev_frame is None:
                f.write(bytes([BYPASS]))
                f.write(bytes(current_frame_int))
                prev_frame=current_frame_int
                master_refs[slot]=current_frame_int.copy()
                frame_index+=1
                continue

            if current_mode==BYPASS:
                out_frame=current_frame_int
            elif current_mode==SEQUENTIAL:
                out_frame = compute_delta(current_frame_int, prev_frame)
            elif current_mode==MASTER:
                ref=master_refs[slot]
                if ref is None:
                    ref=prev_frame
                out_frame=compute_delta(current_frame_int, ref)

            f.write(bytes([current_mode]))
            f.write(bytes(out_frame))
            prev_frame=current_frame_int
            master_refs[slot]=current_frame_int.copy()
            frame_index+=1


def reverse_delta_ml(in_bin,out_txt) :
    FRAME_SIZE=256

    with open(in_bin,"rb") as f_in, open(out_txt,"w") as f_out:
        prev_frame=None
        master_refs=[None]*32
        frame_index=0

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

            f_out.write(" ".join(f"{i:02X}" for i in reconstructed)+"\n")
            prev_frame=reconstructed
            master_refs[slot]=reconstructed.copy()
            frame_index+=1
