from string_hex_stream_with_delta_not_random import generate_telemetry
from telemetry_adaptive_delta import frames_to_delta_binary
from AEC import AEC
from Reverse_delta_and_txt import decompressed_reconstruction
from compare_files import compare

first_time=False #for building the build folder and installing, keep False after first time
testing_sequence=8
days=1
max_changes=64 # max bytes out of 250
#mode="Master Correlated" #"Master Correlated" or "Sequential"
mode="Sequential"

original_telemtery=f"original_telemetry{testing_sequence}.txt"
original_telemtery_delta_bin=f"original_telemetry_delta{testing_sequence}.bin"
compressed_telemtery=f"compressed_telemtery{testing_sequence}.aec"
decompressed_telemtery_delta_bin=f"decompressed_telemtery_delta{testing_sequence}.bin"
reconstruced_telemetry=f"reconstruced_telemetry{testing_sequence}.txt"

frames=generate_telemetry(days, max_changes,mode, original_telemtery)
selected_delta_mode = frames_to_delta_binary(180,frames,original_telemtery_delta_bin )

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

AEC("decompress",
    original_telemtery_delta_bin,
    compressed_telemtery,
    compressed_telemtery,
    decompressed_telemtery_delta_bin)

decompressed_reconstruction(
    decompressed_telemtery_delta_bin,
    reconstruced_telemetry,
    delta_mode=selected_delta_mode,
)

compare(original_telemtery, reconstruced_telemetry)





