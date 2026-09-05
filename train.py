"""Driver script: train and save the model from outside price_model.py itself
so joblib pickles the class under its real module path (price_model.PriceModel)
instead of __main__ — otherwise other scripts can't unpickle it."""
import joblib
from synthetic_data import generate
from price_model import PriceModel, time_based_split

df = generate(60000)
train, test = time_based_split(df, "2025-10-15")
print(f"train={len(train)} test={len(test)}")

model = PriceModel().fit(train)
metrics = model.evaluate(test)
print("Held-out (future dates, never seen in training) evaluation:")
for k, v in metrics.items():
    print(f"  {k}: {v:.4f}")

joblib.dump(model, "price_model.joblib")
print("saved price_model.joblib")
