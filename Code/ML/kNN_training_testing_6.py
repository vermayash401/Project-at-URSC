import pandas as pd
import numpy as np

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import KNeighborsClassifier
from sklearn.metrics import classification_report, confusion_matrix


#load dataset---------------------------------------------------------
df = pd.read_csv("ml_dataset.csv", header=None)

X = df.iloc[:, :-1].values
y = df.iloc[:, -1].values

#train-test split(80-20)-----------------------------------------------
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    stratify=y,
    random_state=42
)

print("Training samples:", len(X_train))
print("Test samples:", len(X_test))

print("Train class distribution:", np.bincount(y_train))
print("Test class distribution:", np.bincount(y_test))

#normalization----------------------------------------------------
scaler = StandardScaler()

X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

#train kNN---------------------------------------------------------
knn = KNeighborsClassifier(n_neighbors=5)

knn.fit(X_train_scaled, y_train)

y_pred_knn = knn.predict(X_test_scaled)

print("Confusion Matrix:")
print(confusion_matrix(y_test, y_pred_knn))

print("\nClassification Report:")
print(classification_report(y_test, y_pred_knn))

print("KNN Accuracy:", knn.score(X_test_scaled, y_test))
print(np.unique(y_test))
print(len(np.unique(y_test)))

# ---------------------------------------------------------
# TEST ON NEW TELEMETRY STREAM
# ---------------------------------------------------------

from behaviour_window_extractor_3 import extract_behaviour_windows
from feature_extraction_4 import extract_features

print("\n--- Testing on NEW telemetry stream ---")

WINDOW_SIZE = 16
test_file = "telemetry_test.hex"   # your new 200-frame file

frames_per_mode = 200 // 4   # because generator made 200 frames

correct = 0
total = 0

for window_index, window in enumerate(
        extract_behaviour_windows(test_file, WINDOW_SIZE)):

    # Extract features from raw telemetry
    features = extract_features(window)

    # Scale using SAME scaler from training
    features_scaled = scaler.transform([features])

    # Predict using trained KNN
    predicted = knn.predict(features_scaled)[0]

    # Compute true label
    start_frame = window_index * WINDOW_SIZE
    true_label = start_frame // frames_per_mode
    true_label = max(0, min(3, true_label))

    if predicted == true_label:
        correct += 1

    total += 1

print("New Stream Windows:", total)
print("New Stream Accuracy:", correct / total)