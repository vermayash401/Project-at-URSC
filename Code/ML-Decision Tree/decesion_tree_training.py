import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.metrics import classification_report, confusion_matrix

DATASET_PATH = "ml_dectree_dataset.csv"

df=pd.read_csv(DATASET_PATH)

FEATURES = [
    "seq_zero_ratio",
    "master_zero_ratio",
    "mean_abs_seq_delta",
    "unique_byte_ratio",
]

X=df[FEATURES]
y=df["label"]

print("Dataset size:", len(df))
print("Class distribution:")
print(df["label"].value_counts())
print("--------------------------------------------------")

X_train, X_test, y_train, y_test = train_test_split(
    X, y,
    test_size=0.2,
    stratify=y,
    random_state=42,
)

tree = DecisionTreeClassifier(
    max_depth=3,          # according to web sources
    min_samples_leaf=50, 
    random_state=42,
)

tree.fit(X_train, y_train)

y_pred = tree.predict(X_test)

print("\nCONFUSION MATRIX")
print(confusion_matrix(y_test, y_pred))

print("\nCLASSIFICATION REPORT")
print(classification_report(y_test, y_pred))

print("\nTREE RULES")
rules = export_text(tree, feature_names=FEATURES)
print(rules)

import joblib
joblib.dump(tree, "decision_tree_model.joblib")
print("Model saved.")