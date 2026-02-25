from string_hex_stream_with_delta_not_random import mixed_telemetry
from ml_dectree_behaviour_delta import frames_to_delta_ml
from feature_extraction import compute_window_features
from AEC import AEC
from reverse_delta import reverse_delta_ml
from compare_files import compare
import os

first_time=False #for building the build folder and installing, keep False after first time

testing_sequence=12
days=2
max_changes = [1, 2, 4, 8, 16, 32, 64] # max bytes out of 250

original_telemtery=f"original_telemetry{testing_sequence}.txt"
original_telemtery_delta_bin=f"original_telemetry_delta{testing_sequence}.bin"
compressed_telemtery=f"compressed_telemtery{testing_sequence}.aec"
decompressed_telemtery_delta_bin=f"decompressed_telemtery_delta{testing_sequence}.bin"
reconstruced_telemetry=f"reconstruced_telemetry{testing_sequence}.txt"

frames=mixed_telemetry(days, max_changes,original_telemtery)
delta_from_model = frames_to_delta_ml(frames,original_telemtery_delta_bin,compute_window_features)

if first_time == True:
    AEC("build",
        original_telemtery_delta_bin,
        compressed_telemtery,
        compressed_telemtery,
        decompressed_telemtery_delta_bin)
else:
    pass

AEC("compress",
    original_telemtery_delta_bin,
    compressed_telemtery,
    compressed_telemtery,
    decompressed_telemtery_delta_bin)

print("COMPRESSEION RATIO (txt to transmiting file) = ", os.path.getsize(original_telemtery)/os.path.getsize(compressed_telemtery), " : 1")
print("Data size reduced by ",  (1-(os.path.getsize(compressed_telemtery)/os.path.getsize(original_telemtery)))*100,"%")

AEC("decompress",
    original_telemtery_delta_bin,
    compressed_telemtery,
    compressed_telemtery,
    decompressed_telemtery_delta_bin)

reverse_delta_ml(
    decompressed_telemtery_delta_bin,
    reconstruced_telemetry)

compare(original_telemtery, reconstruced_telemetry)





