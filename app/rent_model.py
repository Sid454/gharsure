"""Fair-rent predictor: Gradient Boosting on city, locality, BHK, area and furnishing."""
import csv
import pickle
from pathlib import Path

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .db import DATA_DIR

RENT_CSV = DATA_DIR / "rent_data.csv"
MODEL_PATH = DATA_DIR / "models" / "rent.pkl"
FEATURES = ["city", "locality", "bhk", "sqft", "furnishing"]

# Rough monthly rent per sq ft (INR) used ONLY to generate sample training data.
# Replace data/rent_data.csv with a real dataset (e.g. Kaggle "House Rent Prediction").
LOCALITIES = {
    "Bengaluru": {"Koramangala": 45, "Whitefield": 30, "HSR Layout": 40, "Electronic City": 22, "Indiranagar": 50},
    "Pune": {"Hinjewadi": 25, "Kothrud": 28, "Viman Nagar": 32, "Wakad": 24, "Baner": 30},
    "Delhi": {"Saket": 50, "Laxmi Nagar": 28, "Dwarka": 26, "Lajpat Nagar": 45, "Rohini": 22},
    "Mumbai": {"Andheri": 70, "Powai": 75, "Thane": 40, "Bandra": 110, "Navi Mumbai": 35},
    "Hyderabad": {"Gachibowli": 35, "Madhapur": 38, "Kukatpally": 25, "Banjara Hills": 45, "Kondapur": 32},
}
CITY_CENTERS = {
    "Bengaluru": (12.9716, 77.5946), "Pune": (18.5204, 73.8567), "Delhi": (28.6139, 77.2090),
    "Mumbai": (19.0760, 72.8777), "Hyderabad": (17.3850, 78.4867),
}
FURNISH_FACTOR = {"unfurnished": 0.85, "semi-furnished": 1.0, "furnished": 1.2}


def generate_sample_data(n: int = 4000, seed: int = 7) -> None:
    rng = np.random.default_rng(seed)
    RENT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(RENT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FEATURES + ["rent"])
        for _ in range(n):
            city = rng.choice(list(LOCALITIES))
            locality = rng.choice(list(LOCALITIES[city]))
            bhk = int(rng.choice([1, 1, 2, 2, 2, 3, 3, 4]))
            # Wide size range per BHK so small 1RKs and large flats are both covered
            sqft = max(250, int((150 + 400 * bhk) * rng.uniform(0.55, 1.45)))
            furnishing = rng.choice(list(FURNISH_FACTOR))
            rent = LOCALITIES[city][locality] * sqft * FURNISH_FACTOR[furnishing] * rng.normal(1.0, 0.1)
            w.writerow([city, locality, bhk, sqft, furnishing, int(round(rent, -2))])


class RentModel:
    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline

    @classmethod
    def train(cls, csv_path: Path = RENT_CSV) -> "RentModel":
        rows = list(csv.DictReader(open(csv_path, newline="")))
        X = [[r["city"], r["locality"], int(r["bhk"]), int(r["sqft"]), r["furnishing"]] for r in rows]
        y = np.log([float(r["rent"]) for r in rows])  # log-rent: errors become relative
        pipe = Pipeline([
            ("prep", ColumnTransformer(
                [("cat", OneHotEncoder(handle_unknown="ignore"), [0, 1, 4])], remainder="passthrough")),
            ("gbr", GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, random_state=0)),
        ])
        pipe.fit(X, y)
        return cls(pipe)

    def save(self, path: Path = MODEL_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self.pipeline, f)

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "RentModel":
        with open(path, "rb") as f:
            return cls(pickle.load(f))  # noqa: S301 - our own model file

    def predict(self, city: str, locality: str, bhk: int, sqft: int, furnishing: str) -> int:
        pred = self.pipeline.predict([[city, locality, int(bhk), int(sqft), furnishing]])[0]
        return int(round(float(np.exp(pred)), -2))
