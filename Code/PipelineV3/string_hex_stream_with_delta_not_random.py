import random

#32 frames every 16 sec= 2 frame/s
FRAMES_PER_MINUTE = 120
FRAME_SIZE_BYTES = 256
#days = 5
#max_changes=64 #bytes of out 256


def build_frame(block_prefix_5, frame_in_block, payload_250):
    frame = list(block_prefix_5)                  # bytes 0..4 constant per 32-frame block
    frame.append(f"{frame_in_block:02X}")         # byte 5 = frame id 00..1F
    frame.extend(payload_250)                     # bytes 6..255
    return frame


def random_payload(rng, n=250):
    return [f"{rng.getrandbits(8):02X}" for _ in range(n)]


def mutate_payload(prev_payload, rng, max_changes=6):
    if max_changes <= 0:
        return prev_payload.copy()

    out = prev_payload.copy()
    changes = rng.randint(1, max_changes)
    for _ in range(changes):
        idx = rng.randrange(len(out))
        out[idx] = f"{rng.getrandbits(8):02X}"
    return out


def generate_month_frames(days=1, max_changes=6, frame_mode=[0.33,0.33,0.33], seed=None):
    rng = random.Random(seed)
    total_frames = int(days * 24 * 60 * FRAMES_PER_MINUTE)
    frames = []
    last_progress_len = 0

    # split equally into 3 modes (contiguous thirds)
    n_same = total_frames // 3
    n_low_var = total_frames // 3
    n_random = total_frames - n_same - n_low_var

    # state for modes
    same_payload_global = random_payload(rng, 250)
    low_var_prev_payload = random_payload(rng, 250)

    for i in range(total_frames):
        frame_in_block = i % 32
        if frame_in_block == 0:
            block_prefix_5 = [f"{rng.getrandbits(8):02X}" for _ in range(5)]
        if  frame_mode==[0.33,0.33,0.33]:
            # choose mode by frame index
            if i < n_same:
                mode = "same"
            elif i < n_same + n_low_var:
                mode = "low_var"
            else:
                mode = "random"
        
        elif frame_mode==[0,0.66,0.33]:
            # choose mode by frame index
            if i < n_same:
                mode = "low_var"
            elif i < n_same + n_low_var:
                mode = "low_var"
            else:
                mode = "random"

        elif frame_mode==[0,10,0]:
            mode = "low_var"
        
        elif frame_mode==[0,0,10]:
            mode = "random"

        if mode == "same":
            payload = same_payload_global

        elif mode == "low_var":
            low_var_prev_payload = mutate_payload(low_var_prev_payload, rng, max_changes)
            payload = low_var_prev_payload

        else:  # random
            payload = random_payload(rng, 250)

        frames.append(build_frame(block_prefix_5, frame_in_block, payload))

        #lightweight progress print
        if (i + 1) % 10000 == 0 or (i + 1) == total_frames:
            progress_text = f"{total_frames - (i + 1)} frames left"
            last_progress_len = len(progress_text)
            print(f"\r{progress_text}", end="", flush=True)

    if last_progress_len > 0:
        print("\r" + (" " * last_progress_len) + "\r", end="", flush=True)

    return frames


def generate_master_correlated_frames(days=1, max_changes=6,frame_mode=[0.33,0.33,0.33], seed=None):
    rng = random.Random(seed)
    total_frames = int(days * 24 * 60 * FRAMES_PER_MINUTE)
    frames = []
    last_progress_len = 0

    # split equally into 3 modes (contiguous thirds)
    n_same = total_frames // 3
    n_low_var_master = total_frames // 3
    n_random = total_frames - n_same - n_low_var_master

    # SAME mode state: one payload for entire dataset segment
    same_payload_global = random_payload(rng, 250)

    # LOW_VAR_MASTER mode state: independent payload buffer for each frame index 0..31
    master_index_states = [random_payload(rng, 250) for _ in range(32)]

    for i in range(total_frames):
        frame_in_block = i % 32
        if frame_in_block == 0:
            block_prefix_5 = [f"{rng.getrandbits(8):02X}" for _ in range(5)]

        if  frame_mode==[0.33,0.33,0.33]:
            # choose mode by frame index
            if i < n_same:
                mode = "same"
            elif i < n_same + n_low_var_master:
                mode = "low_var_master"
            else:
                mode = "random"
        
        elif frame_mode==[0,0.66,0.33]:
            # choose mode by frame index
            if i < n_same:
                mode = "low_var_master"
            elif i < n_same + n_low_var_master:
                mode = "low_var_master"
            else:
                mode = "random"

        elif frame_mode==[0,10,0]:
            mode = "low_var_master"
        
        elif frame_mode==[0,0,10]:
            mode = "random"

        if mode == "same":
            payload = same_payload_global

        elif mode == "low_var_master":
            # Apply slow evolution once per master frame for each index state.
            if frame_in_block == 0:
                for k in range(32):
                    master_index_states[k] = mutate_payload(master_index_states[k], rng, max_changes)
            payload = master_index_states[frame_in_block]

        else:  # random
            payload = random_payload(rng, 250)

        frames.append(build_frame(block_prefix_5, frame_in_block, payload))

        # lightweight progress print
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


def txt_hex_to_binary(in_txt, out_bin):
    with open(in_txt, "r", encoding="utf-8") as f_in, open(out_bin, "wb") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            hex_string = line.replace(" ", "")
            binary_data = bytes.fromhex(hex_string)
            f_out.write(binary_data)

def frames_to_delta_binary(frames, out_bin):
    with open(out_bin, "wb") as f:
        prev = None

        for frame in frames:
            # convert hex strings to integers
            current = [int(b, 16) for b in frame]

            if prev is None:
                # first frame stored raw
                f.write(bytes(current))
            else:
                # compute signed delta and wrap to 0–255
                deltas = []
                for c, p in zip(current, prev):
                    d = c - p          # signed delta
                    d &= 0xFF          # wrap into unsigned byte
                    deltas.append(d)

                f.write(bytes(deltas))

            prev = current




def generate_telemetry(days, max_changes,frame_mode,mode="Sequential", txt_output="spacecraft_framesX.txt"): #, bin_output= "spacecraft_framesX_delta.bin",):
    print("------------------------------------------------------------------------")
    if mode == "Master Correlated":
        frames = generate_master_correlated_frames(days, max_changes,frame_mode)
    else:
        frames = generate_month_frames(days, max_changes,frame_mode)
    #print(frames[0], "\n", frames[1])
    save_frames_to_txt(frames, path=txt_output)
    #frames_to_delta_binary(frames, bin_output)
    print("TELEMETRY GENERATED: ", len(frames), "frames")
    #print(f"Saved {len(frames)} frames to", txt_output, "and", bin_output)
    print("------------------------------------------------------------------------")
    return frames
    

def mixed_telemetry (days=0.05, max_changes=[1, 2, 4, 8, 16, 32, 64],txt_output="spacecraft_framesX.txt"):

    each_regime_data_duration_in_days=days/(len(max_changes)+2)
    frames_same = generate_month_frames(each_regime_data_duration_in_days,0,[0,10,0])
    frames_random = generate_month_frames(each_regime_data_duration_in_days,0,[0,0,10])# here max changes doesnt matter
    frames_related=[]
    for i in max_changes:
        frames_master = generate_master_correlated_frames(each_regime_data_duration_in_days,i,[0,10,0])
        frames_seq = generate_month_frames(each_regime_data_duration_in_days,i,[0,10,0])
        frames_related.extend(frames_master)
        frames_related.extend(frames_seq)
    frames=frames_same+frames_related+frames_random
    save_frames_to_txt(frames, path=txt_output)
    return frames
