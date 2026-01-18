import math

input_file='telemetry_stream.hex'

k=10

def hex_string_to_int(value):
    return int(value,16)

def euc_dist(p1,p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

data=[]

with open(input_file,'r') as file:
    for i in file:
        bytes_hex=i.strip().split()

        #frame looks like | FC CA 1D F9 | 00 | 0E | 04 AF | A5 A5 |

        satsourceA_telemetry=hex_string_to_int(bytes_hex[5])
        satsourceA=satsourceA_telemetry+273

        satsourceB_telemetry_MSB=hex_string_to_int(bytes_hex[6])
        satsourceB_telemetry_LSB=hex_string_to_int(bytes_hex[7])
        satsourceB= ((satsourceB_telemetry_MSB<<8) | satsourceB_telemetry_LSB) /100
                     
        data.append([satsourceA, satsourceB])


################################## kNN ###############################################

def knn(query_point, dataset, k):
    distances = []

    for idx, point in enumerate(dataset):
        dist = euc_dist(query_point, point)
        distances.append((dist, idx, point))

    # Sort by distance
    distances.sort(key=lambda x: x[0])

    # Return k nearest neighbours (excluding itself)
    return distances[1:k+1]

################################## kNN ################################################

query_index=10
query_point=data[query_index]

neighbors=knn(query_point, data, k)

print(f"\nQuery Frame {query_index}")
print(f"Temperature = {query_point[0]} K, Voltage = {query_point[1]:.2f} V\n")

print("Nearest Neighbours:")
for dist, idx, point in neighbors:
    print(f"Frame {idx}: Temp = {point[0]} K, Volt = {point[1]:.2f} V, Distance = {dist:.3f}")
