from dataset_generation_loop import generate_ml_dataset
from string_hex_stream_with_delta_not_random import generate_month_frames
from string_hex_stream_with_delta_not_random import generate_master_correlated_frames
from string_hex_stream_with_delta_not_random import save_frames_to_txt
from AEC import AEC
import random
import csv
from collections import Counter


#1 million frames of telemtery almost = 6 DAYS-------2 days each mode- bypass,sequential,master
days=2
max_changes = [1, 2, 4, 8, 16, 32, 64]
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
print("frames_same:", len(frames_same))
print("frames_related:", len(frames_related))
print("frames_random:", len(frames_random))

def AEC_compress_wrapper(in_bin_path, out_aec_path):
    AEC("compress",
        in_bin_path,
        out_aec_path,
        None,
        None)

def print_dataset_stats(csv_path):
    label_counter=Counter()
    total=0

    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label_counter[int(row["label"])]+=1
            total+=1

    print("\nDATASET SUMMARY")
    print(f"Total samples: {total}")
    print(f"BYPASS (0): {label_counter[0]}")
    print(f"SEQUENTIAL (1): {label_counter[1]}")
    print(f"MASTER (2): {label_counter[2]}")

print(f"Total frames generated: {len(frames)}")

generate_ml_dataset(frames,
                    AEC_compress_wrapper,
                    "ml_dectree_dataset.csv")

print_dataset_stats("ml_dectree_dataset.csv")

