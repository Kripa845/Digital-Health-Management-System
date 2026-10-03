import pandas as pd

df = pd.read_csv("ml/data/dataset.csv")
print(df.shape)
print(df.columns.tolist())
print(df["Disease"].nunique(), "diseases")
print(df.head())