from string_hex_stream_with_delta_not_random import generate_telemetry
from AEC import AEC
from Reverse_delta_and_txt import decompressed_reconstruction
from compare_files import compare

first_time=False #for building the build folder and installing, keep False after first time

original_telemtery="original_telemetry7.txt"
original_telemtery_delta_bin="original_telemetry_delta7.bin"
compressed_telemtery="compressed_telemtery7.aec"
decompressed_telemtery_delta_bin="decompressed_telemtery_delta7.bin"
reconstruced_telemetry="reconstruced_telemetry7.txt"

days=5
max_changes=32

generate_telemetry(days, max_changes, original_telemtery, original_telemtery_delta_bin)

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

decompressed_reconstruction(decompressed_telemtery_delta_bin,reconstruced_telemetry)

compare(original_telemtery, reconstruced_telemetry)





