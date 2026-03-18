import math
from collections import Counter


'''w=[
  [10, 20, 30],
  [11, 21, 31],
  [12, 22, 32],
  [13, 23, 33],
]'''



def extract_features(window):
    """
    Convert one behaviour window (list of payloads) into a flat feature vector.

    Features (in order):
    1) Mean of each payload byte position                -> P values
    2) Variance of each payload byte position            -> P values
    3) Mean absolute temporal delta per byte position    -> P values
    4) Variance of temporal deltas per byte position     -> P values
    5) Normalized longest run length of identical payloads -> 1 value
    6) Shannon entropy of all bytes in the window        -> 1 value
    """
    if not window:
        return []

    num_frames = len(window)
    payload_size = len(window[0])

    # Validate consistent payload shape
    for i, payload in enumerate(window):
        if len(payload) != payload_size:
            raise ValueError(
                f"Inconsistent payload size at index {i}: "
                f"expected {payload_size}, got {len(payload)}"
            )

    def mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    def variance(xs):
        if not xs:
            return 0.0
        m = mean(xs)
        return sum((x - m) ** 2 for x in xs) / len(xs)  # population variance

    features = []

    # 1) Mean per byte position
    for j in range(payload_size):
        col = [frame[j] for frame in window]
        features.append(float(mean(col)))

    # 2) Variance per byte position
    for j in range(payload_size):
        col = [frame[j] for frame in window]
        features.append(float(variance(col)))

    # Build temporal deltas (frame_t - frame_{t-1}) for each byte position
    deltas_per_pos = [[] for _ in range(payload_size)]
    for t in range(1, num_frames):
        prev_frame = window[t - 1]
        curr_frame = window[t]
        for j in range(payload_size):
            deltas_per_pos[j].append(curr_frame[j] - prev_frame[j])

    # 3) Mean absolute temporal delta per byte position
    for j in range(payload_size):
        abs_deltas = [abs(d) for d in deltas_per_pos[j]]
        features.append(float(mean(abs_deltas)))

    # 4) Variance of temporal deltas per byte position (signed deltas)
    for j in range(payload_size):
        features.append(float(variance(deltas_per_pos[j])))

    # 5) Normalized longest run length of identical payloads
    longest_run = 1
    current_run = 1
    for t in range(1, num_frames):
        if window[t] == window[t - 1]:
            current_run += 1
            if current_run > longest_run:
                longest_run = current_run
        else:
            current_run = 1
    normalized_longest_run = longest_run / num_frames
    features.append(float(normalized_longest_run))

    # 6) Shannon entropy of all bytes in the window
    all_bytes = [b for frame in window for b in frame]
    total = len(all_bytes)
    if total == 0:
        entropy = 0.0
    else:
        counts = Counter(all_bytes)
        entropy = 0.0
        for c in counts.values():
            p = c / total
            entropy -= p * math.log2(p)
    features.append(float(entropy))
    #print(features)
    return features


#extract_features(w)