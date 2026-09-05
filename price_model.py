"""
Core price model. Predicts log(price) for a round-trip search from:
    route, departure day-of-week, departure month, days_out (lead time),
    nights (trip length), stops, airline

Trains three HistGradientBoostingRegressor models with quantile loss
(p10 / p50 / p90) instead of one point estimate — this is what lets the
date-optimizer and buy/wait tools reason about *uncertainty*, not just a
single number, which matters because real fares are noisy/quota-driven.

sklearn's HistGradientBoostingRegressor is used (not XGBoost/LightGBM) so
this runs with zero extra installs; swap in LightGBM/XGBoost later for a
few extra points of accuracy on real data — the feature/label pipeline
below stays identical.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error, mean_squared_error
from sklearn.preprocessing import OrdinalEncoder

FEATURES = ["route", "dep_dow", "dep_month", "days_out", "nights", "stops", "airline"]
CATEGORICAL = ["route", "airline"]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["dep_dow"] = out["departure_date"].dt.dayofweek
    out["dep_month"] = out["departure_date"].dt.month
    return out[FEATURES + (["price"] if "price" in out.columns else [])]


class PriceModel:
    """Wraps p10/p50/p90 quantile regressors behind one predict() API."""

    def __init__(self):
        self.models: dict[float, HistGradientBoostingRegressor] = {}
        self.cat_idx = None
        self.encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)

    def fit(self, df: pd.DataFrame):
        feat = build_features(df)
        X = feat[FEATURES].copy()
        X[CATEGORICAL] = self.encoder.fit_transform(X[CATEGORICAL])
        y = np.log(feat["price"].values)
        self.cat_idx = [X.columns.get_loc(c) for c in CATEGORICAL]

        for q in (0.1, 0.5, 0.9):
            model = HistGradientBoostingRegressor(
                loss="quantile",
                quantile=q,
                max_iter=300,
                learning_rate=0.06,
                max_depth=6,
                categorical_features=self.cat_idx,
                random_state=0,
            )
            model.fit(X, y)
            self.models[q] = model
        self._X_columns = list(X.columns)
        return self

    def _prep(self, df: pd.DataFrame) -> pd.DataFrame:
        feat = build_features(df)
        X = feat[FEATURES].copy()
        X[CATEGORICAL] = self.encoder.transform(X[CATEGORICAL])
        return X[self._X_columns]

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Returns predicted p10/p50/p90 PRICE (not log) for each row."""
        X = self._prep(df)
        preds = {}
        for q, model in self.models.items():
            preds[f"p{int(q*100)}"] = np.exp(model.predict(X))
        return pd.DataFrame(preds, index=df.index)

    def evaluate(self, df: pd.DataFrame) -> dict:
        preds = self.predict(df)
        y_true = df["price"].values
        y_pred = preds["p50"].values
        return {
            "MAPE": mean_absolute_percentage_error(y_true, y_pred),
            "RMSE": mean_squared_error(y_true, y_pred) ** 0.5,
            "p10_coverage": float((y_true >= preds["p10"]).mean()),  # want ~0.90
            "p90_coverage": float((y_true <= preds["p90"]).mean()),  # want ~0.90
        }


def time_based_split(df: pd.DataFrame, cutoff: str):
    cutoff = pd.Timestamp(cutoff)
    train = df[df["search_date"] < cutoff].reset_index(drop=True)
    test = df[df["search_date"] >= cutoff].reset_index(drop=True)
    return train, test


if __name__ == "__main__":
    from synthetic_data import generate

    df = generate(60000)
    train, test = time_based_split(df, "2025-10-15")  # last ~2.5 months held out
    print(f"train={len(train)} test={len(test)}")

    model = PriceModel().fit(train)
    metrics = model.evaluate(test)
    print("Held-out (future dates, never seen in training) evaluation:")
    for k, v in metrics.items():
        print(f"  {k}: {v:.4f}")

    import joblib
    joblib.dump(model, "price_model.joblib")
    print("saved price_model.joblib")
