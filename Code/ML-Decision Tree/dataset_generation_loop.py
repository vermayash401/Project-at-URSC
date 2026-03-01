import csv
from feature_extraction import compute_window_features
from label_generator import best_strategy_for_window

WINDOW_SIZE = 32

def generate_ml_dataset(frames,aec_compress_func,output_csv="ml_dataset.csv"):
   
    dataset_rows=[]
    current_window=[]
    prev_window=None

    window_count=0

    for frame in frames:
        current_window.append(frame)

        #when window filled:
        if len(current_window)==WINDOW_SIZE:

            F1,F2,F3,F4=compute_window_features(current_window,prev_window)

            #find delta mode
            label=best_strategy_for_window(current_window,prev_window,aec_compress_func)

            dataset_rows.append([F1,F2,F3,F4,label])

            #progress print
            window_count+=1
            if window_count % 100 == 0:
                print(f"Processed windows: {window_count}")

            #for next window
            prev_window=current_window
            current_window=[]

    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)

        #row headers
        writer.writerow(["seq_zero_ratio","master_zero_ratio","mean_abs_seq_delta","unique_byte_ratio","label"])
        writer.writerows(dataset_rows)
    print(f"Dataset saved: {output_csv}")
    print(f"Total samples: {len(dataset_rows)}")
    return dataset_rows