import math

#MASTER_FRAME_SIZE = 32
#EVAL_SECONDS = 180  # 1 master frame every 60 sec
#FRAMES_PER_SECOND = 32 / 60
#EVAL_FRAMES = int(EVAL_SECONDS * FRAMES_PER_SECOND)


def frames_to_delta_binary(EVAL_SECONDS, frames, out_bin):
    EVAL_FRAMES = int(EVAL_SECONDS * 32/60)
    def wrapped_delta(current, reference):
        return [(c - r) & 0xFF for c, r in zip(current, reference)]

    def entropy_from_hist(hist, total_count):
        if total_count <= 0:
            return 0.0
        entropy = 0.0
        for count in hist:
            if count:
                p = count / total_count
                entropy -= p * math.log2(p)
        return entropy

    eval_limit = max(0, EVAL_FRAMES)

    with open(out_bin, "wb") as f:
        sequential_prev = None
        master_refs = [None] * 32  # frame index 0..31 -> last master frame copy
        frame_idx = 0
        selected_mode = None  # "sequential" or "master_aligned"

        # Evaluation-window buffers (only first eval_limit frames are dual-computed)
        eval_seq_deltas = []
        eval_master_deltas = []
        seq_zero_count = 0
        master_zero_count = 0
        seq_hist = [0] * 256
        master_hist = [0] * 256
        seq_total = 0
        master_total = 0

        for frame in frames:
            current = [int(b, 16) for b in frame]
            slot = frame_idx % 32

            if sequential_prev is None:
                # First frame is always raw and unchanged in output format.
                f.write(bytes(current))
            else:
                master_ref = master_refs[slot] if master_refs[slot] is not None else sequential_prev
                seq_delta = wrapped_delta(current, sequential_prev)
                master_delta = wrapped_delta(current, master_ref)

                if frame_idx < eval_limit:
                    eval_seq_deltas.append(seq_delta)
                    eval_master_deltas.append(master_delta)

                    for b in seq_delta:
                        if b == 0:
                            seq_zero_count += 1
                        seq_hist[b] += 1
                    seq_total += len(seq_delta)

                    for b in master_delta:
                        if b == 0:
                            master_zero_count += 1
                        master_hist[b] += 1
                    master_total += len(master_delta)
                else:
                    if selected_mode is None:
                        seq_entropy = entropy_from_hist(seq_hist, seq_total)
                        master_entropy = entropy_from_hist(master_hist, master_total)

                        if master_zero_count > seq_zero_count:
                            selected_mode = "master_aligned"
                        elif master_zero_count < seq_zero_count:
                            selected_mode = "sequential"
                        elif master_entropy < seq_entropy:
                            selected_mode = "master_aligned"
                        else:
                            selected_mode = "sequential"

                        if selected_mode == "master_aligned":
                            for d in eval_master_deltas:
                                f.write(bytes(d))
                        else:
                            for d in eval_seq_deltas:
                                f.write(bytes(d))

                        eval_seq_deltas.clear()
                        eval_master_deltas.clear()

                        if selected_mode == "master_aligned":

                            print("Delta mode selected: MASTER-FRAME ALIGNED")
                            print("------------------------------------------------------------------------")
                        else:
                            
                            print("Delta mode selected: SEQUENTIAL")
                            print("------------------------------------------------------------------------")

                    f.write(bytes(master_delta if selected_mode == "master_aligned" else seq_delta))

            # State handling:
            # sequential_prev is always the immediate prior frame.
            # master_refs[slot] stores the most recent frame for this slot from the previous master frame.
            master_refs[slot] = current.copy()
            sequential_prev = current
            frame_idx += 1

        # If stream ended before leaving evaluation window, finalize choice and flush buffered deltas.
        if selected_mode is None and frame_idx > 1:
            seq_entropy = entropy_from_hist(seq_hist, seq_total)
            master_entropy = entropy_from_hist(master_hist, master_total)

            if master_zero_count > seq_zero_count:
                selected_mode = "master_aligned"
            elif master_zero_count < seq_zero_count:
                selected_mode = "sequential"
            elif master_entropy < seq_entropy:
                selected_mode = "master_aligned"
            else:
                selected_mode = "sequential"
            
            if selected_mode == "master_aligned":
                print("------------------------------------------------------------------------")
                print("Delta mode selected: MASTER-FRAME ALIGNED")
                print("------------------------------------------------------------------------")
            else:
                print("------------------------------------------------------------------------")
                print("Delta mode selected: SEQUENTIAL")
                print("------------------------------------------------------------------------")
            if selected_mode == "master_aligned":
                for d in eval_master_deltas:
                    f.write(bytes(d))
            else:
                for d in eval_seq_deltas:
                    f.write(bytes(d))

    if selected_mode is None:
        selected_mode = "sequential"
    return selected_mode
