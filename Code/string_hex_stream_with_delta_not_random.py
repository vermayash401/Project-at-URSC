import random

FRAMES_PER_MINUTE = 32
FRAME_SIZE_BYTES = 256
days = 1


def build_frame(block_prefix_5, frame_in_block, payload_250):
    frame = list(block_prefix_5)                  # bytes 0..4 constant per 32-frame block
    frame.append(f"{frame_in_block:02X}")         # byte 5 = frame id 00..1F
    frame.extend(payload_250)                     # bytes 6..255
    return frame


def random_payload(rng, n=250):
    return [f"{rng.getrandbits(8):02X}" for _ in range(n)]


def mutate_payload(prev_payload, rng, max_changes=6):
    # small variation: mutate only a few positions
    out = prev_payload.copy()
    changes = rng.randint(1, max_changes)
    for _ in range(changes):
        idx = rng.randrange(len(out))
        out[idx] = f"{rng.getrandbits(8):02X}"
    return out


def generate_month_frames(days=1, seed=None):
    rng = random.Random(seed)
    total_frames = days * 24 * 60 * FRAMES_PER_MINUTE
    frames = []

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

        # choose mode by frame index
        if i < n_same:
            mode = "same"
        elif i < n_same + n_low_var:
            mode = "low_var"
        else:
            mode = "random"

        if mode == "same":
            payload = same_payload_global

        elif mode == "low_var":
            low_var_prev_payload = mutate_payload(low_var_prev_payload, rng, max_changes=6)
            payload = low_var_prev_payload

        else:  # random
            payload = random_payload(rng, 250)

        frames.append(build_frame(block_prefix_5, frame_in_block, payload))

        # lightweight progress print
        if (i + 1) % 10000 == 0 or (i + 1) == total_frames:
            print(f"{total_frames - (i + 1)} frames left")

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



if __name__ == "__main__":
    frames = generate_month_frames(days, seed=None)
    print(frames[0], "\n", frames[1])
    save_frames_to_txt(frames, path="spacecraft_frames2.txt")
    print(f"Saved {len(frames)} frames to spacecraft_frames2.txt")
    frames_to_delta_binary(frames, "spacecraft_frames2_delta.bin")

    print("and .bin")
