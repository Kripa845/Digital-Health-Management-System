import pandas as pd

df = pd.read_csv("ml/data/train/ddxplus_binary.csv")   # written by python -m ml.ddxplus_adapter
print(df.shape)
print(df.columns.tolist())
print(df["prognosis"].nunique(), "illnesses")
print(df.head())
