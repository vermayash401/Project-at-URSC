import pandas as pd
import numpy as np

DATASET = "ml_dectree_dataset.csv"

df = pd.read_csv(DATASET)

# Your learned thresholds
SEQ_THRESH = 0.44
MASTER_THRESH = 0.42

# Split by class
bypass = df[df["label"] == 0]
seq = df[df["label"] == 1]
master = df[df["label"] == 2]

print("====================================")
print("THRESHOLD MARGIN ANALYSIS")
print("====================================")

def margin_stats(values, thresh, name):
    dist = np.abs(values - thresh)
    print(f"\n{name}")
    print(f"  min distance to threshold: {dist.min():.4f}")
    print(f"  mean distance to threshold: {dist.mean():.4f}")
    print(f"  5th percentile distance: {np.percentile(dist,5):.4f}")

# -------------------------------
# Sequential boundary check
# -------------------------------
print("\n--- Sequential boundary (F1 vs 0.44) ---")

margin_stats(
    seq["seq_zero_ratio"],
    SEQ_THRESH,
    "SEQUENTIAL class"
)

margin_stats(
    bypass["seq_zero_ratio"],
    SEQ_THRESH,
    "BYPASS class"
)

margin_stats(
    master["seq_zero_ratio"],
    SEQ_THRESH,
    "MASTER class"
)

# -------------------------------
# Master boundary check
# -------------------------------
print("\n--- Master boundary (F2 vs 0.42) ---")

margin_stats(
    bypass["master_zero_ratio"],
    MASTER_THRESH,
    "BYPASS class"
)

margin_stats(
    master["master_zero_ratio"],
    MASTER_THRESH,
    "MASTER class"
)

margin_stats(
    seq["master_zero_ratio"],
    MASTER_THRESH,
    "SEQUENTIAL class"
)

print("\n====================================")
print("INTERPRETATION GUIDE")
print("====================================")
print("If min distance > 0.05 → VERY SAFE")
print("If min distance > 0.02 → SAFE")
print("If min distance < 0.01 → borderline")
print("====================================")