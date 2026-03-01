import joblib
from feature_extraction import compute_window_features
from label_generator import best_strategy_for_window  # your OG AEC labeler
from label_generator import AEC_compress_wrapper

WINDOW_SIZE = 32

# --------------------------------------------------
# Load trained model
# --------------------------------------------------
tree = joblib.load("decision_tree_model.joblib")

print("Model loaded.")
print("--------------------------------------------------")

# --------------------------------------------------
# Generate NEW telemetry stream (fresh seed!)
# --------------------------------------------------
from string_hex_stream_with_delta_not_random import generate_month_frames

frames = generate_month_frames(
    days=0.05,
    max_changes=4,
    frame_mode=[0.33, 0.33, 0.33],
    seed=999  
)

print("New telemetry generated:", len(frames))

# --------------------------------------------------
# Window evaluation
# --------------------------------------------------
correct = 0
total = 0

current_window = []
prev_window = None

for frame in frames:
    current_window.append(frame)

    if len(current_window) == WINDOW_SIZE:

        # ----- features -----
        F1, F2, F3, F4 = compute_window_features(
            current_window,
            prev_window,
        )

        # ----- ML prediction -----
        pred = tree.predict([[F1, F2, F3, F4]])[0]

        # ----- ground truth (AEC based) -----
        truth, _, _ = best_strategy_for_window(
            current_window,
            prev_window, 
        )

        if pred == truth:
            correct += 1

        total += 1
        prev_window = current_window
        current_window = []

# --------------------------------------------------
# Results
# --------------------------------------------------
accuracy = correct / total if total > 0 else 0

print("--------------------------------------------------")
print("External validation windows:", total)
print("Agreement with ground truth:", accuracy)
print("--------------------------------------------------")