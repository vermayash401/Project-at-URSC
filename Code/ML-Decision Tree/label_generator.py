import tempfile
import os
from AEC import AEC

BYPASS=0
SEQUENTIAL=1
MASTER=2

def AEC_compress_wrapper(in_bin_path, out_aec_path):
    AEC("compress",
        in_bin_path,
        out_aec_path,
        None,
        None)

def best_strategy_for_window(current_window,prev_window,aec_compress_func):
   
    FRAME_SIZE=len(current_window[0])

    def write_delta_file(frames, refs, mode, out_path):
        with open(out_path, "wb") as f:
            prev=None

            #returning index,frame from frames
            for idx, frame in enumerate(frames):
                    
                #hex to int
                curr=[int(b, 16) for b in frame]

                if idx==0 and mode=="sequential":
                    f.write(bytes(curr))
                else:
                    if mode=="sequential":
                        reference=prev
                    elif mode=="master":
                        reference=refs[idx]
                    else:
                        raise ValueError("unknown mode")
                    delta=[(i-j) & 0xFF for i,j in zip(curr, reference)]
                    f.write(bytes(delta))
                prev=curr

    #temp files for context only
    with tempfile.TemporaryDirectory() as tmp:
        seq_bin = os.path.join(tmp, "seq.bin")
        seq_aec = os.path.join(tmp, "seq.aec")

        write_delta_file(current_window, None, "sequential", seq_bin)
        aec_compress_func(seq_bin, seq_aec)

        raw_size=os.path.getsize(seq_bin)
        seq_size=os.path.getsize(seq_aec)
        CR_seq=raw_size/seq_size if seq_size > 0 else 0.0

        if prev_window is None:
            CR_master=None
        else:
            master_bin=os.path.join(tmp, "master.bin")
            master_aec=os.path.join(tmp, "master.aec")

            master_refs = [[int(b, 16) for b in frame]for frame in prev_window]

            write_delta_file(current_window, master_refs, "master", master_bin)
            aec_compress_func(master_bin, master_aec)

            master_size=os.path.getsize(master_aec)
            CR_master=raw_size / master_size if master_size > 0 else 0.0

    CR_bypass=1.0
    difference=0.02

    # first window case
    if CR_master is None:
        if CR_seq <= CR_bypass:
            return BYPASS
        return SEQUENTIAL

    # both bad
    if CR_seq <= CR_bypass and CR_master <= CR_bypass:
        return BYPASS

    # sequential wins
    if (CR_seq > CR_master) and (CR_seq > CR_bypass):
        return SEQUENTIAL

    # master wins
    if (CR_master > CR_seq) and (CR_master > CR_bypass):
        return MASTER

    # tie-sequential
    if abs(CR_seq-CR_master)<difference:
        return SEQUENTIAL

    return SEQUENTIAL if CR_seq >= CR_master else MASTER