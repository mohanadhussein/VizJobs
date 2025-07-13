import pandas as pd
import numpy as np
import joblib
from pathlib import Path
import argparse

from sklearn.preprocessing import OneHotEncoder
from thefuzz import fuzz

# Return X in the exact order/shape the model was trained on.
def make_X(model, df_raw: pd.DataFrame) -> pd.DataFrame:
    try:
        expected = list(model.feature_names_in_)
    except AttributeError:
        expected = list(model.named_steps["preprocessor"].feature_names_in_)

    X = pd.DataFrame(index=df_raw.index)
    for col in expected:
        # Use blank string if column missing
        X[col] = df_raw.get(col, "")
    return X[expected] if len(expected) > 1 else X[expected[0]]


# Recursively search for a OneHotEncoder in a pipeline.
def _find_onehot(est):
    if isinstance(est, OneHotEncoder):
        return est
    if hasattr(est, "named_steps"):
        for step in est.named_steps.values():
            ohe = _find_onehot(step)
            if ohe is not None:
                return ohe
    return None


# Extract allowed category values from the model’s OneHotEncoder for a column.
def get_ohe_categories(model, col_name):
    ct = model.named_steps["preprocessor"]
    for name, transformer, cols in ct.transformers_:
        if col_name in cols:
            ohe = _find_onehot(transformer)
            if ohe is None:
                raise RuntimeError(f"No OneHotEncoder in '{name}'")
            idx = list(cols).index(col_name)
            return {str(c) for c in ohe.categories_[idx]}
    raise ValueError(f"Column '{col_name}' not found in ColumnTransformer")


# Fuzzy-match a value to the closest entry in the known_set.
def map_to_known(val, known_set, threshold=80):
    if pd.isna(val):
        return "Other"
    val_str = str(val).lower()
    best_match = "Other"
    best_score = 0
    for known in known_set:
        score = fuzz.token_set_ratio(val_str, known.lower())
        if score > best_score:
            best_match = known
            best_score = score
    return best_match if best_score >= threshold else "Other"


# Map state values using exact matching 
# (due to the abbreviation, fuzzy matching does not work)
def map_to_known_states(val, known_set):
    if pd.isna(val):
        return "Other"
    val_str = str(val).strip().upper()
    return val_str if val_str in known_set else "Other"


# Return median salary from lookup_dict based on fuzzy match.
def get_reference_median(val, lookup_dict, threshold=80):
    if pd.isna(val):
        return np.nan
    val_str = str(val).lower()
    best_match = "Other"
    best_score = 0
    for known in lookup_dict.keys():
        score = fuzz.token_set_ratio(val_str, known.lower())
        if score > best_score:
            best_match = known
            best_score = score
    return lookup_dict[best_match] if best_score >= threshold else np.nan


# Calculate adjusted base salary using state and job level multipliers
def adjusted_base(row, state_factors, job_level_factors):
    base = row["base_salary"]
    state = row["state"]
    level = str(row["correct_job_level"]).strip().lower()
    state_factor = state_factors.get(state, 1.0)
    level_factor = job_level_factors.get(level, 1.0)
    if pd.notna(base):
        adjusted = base * state_factor * level_factor
        return round(adjusted)
    else:
        return np.nan


def main():
    parser = argparse.ArgumentParser(add_help=True)

    parser.add_argument(
        "-I", "--input",
        help=(
            "The input file with the following variables as columns: "
            "('title', 'correct_job_level', 'state'). Also see README.md."
        ),
        required=False,
        type=str,
        default="combined_job_search.csv"
    )

    parser.add_argument(
        "-O", "--output",
        help=(
            "The output file to save predictions. Also see README.md."
        ),
        required=False,
        type=str,
        default="combined_job_search_predictions.csv"
    )

    args = parser.parse_args()
    input_file_name = args.input
    output_file_name = args.output

    # Path to the model
    MODEL_PATHS = {
        "poly_deg2": Path("resources") / "salary_predictor.pkl"
    }


    # Load the original job dataset
    df = pd.read_csv(input_file_name)

    # Create a copy to store results separately
    results_df = df.copy()

    # Predictions based on the input data:
    for label, pkl_path in MODEL_PATHS.items():
        print(f"📤 Loading model: {label}")
        model = joblib.load(pkl_path)

        # Step 1: Extract known categories from the model
        allowed_titles = get_ohe_categories(model, "title")
        allowed_industries = get_ohe_categories(model, "company_industry")
        allowed_levels = get_ohe_categories(model, "correct_job_level")
        allowed_states = get_ohe_categories(model, "state")

        # Step 2: Map user values to known categories
        df["title"] = df["title"].apply(lambda x: map_to_known(x, allowed_titles))
        df["company_industry"] = df["company_industry"].apply(lambda x: map_to_known(x, allowed_industries))
        df["correct_job_level"] = df["correct_job_level"].apply(lambda x: map_to_known(x, allowed_levels))
        df["state"] = df["state"].apply(lambda x: map_to_known_states(x, allowed_states))

        # Step 3: Ensure all required columns are present
        required_cols = {"title", "company_industry", "correct_job_level", "state"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"❗ Missing columns for prediction: {missing}")

        # Step 4: Create X and predict
        X = make_X(model, results_df)
        print(f"📥 Predicting on shape {np.shape(X)} …")
        y_pred = np.asarray(model.predict(X))

        # Step 5: Store predictions with specific column names
        target_names = ["p10", "median", "p90"]
        if y_pred.ndim == 1:
            results_df[f"{label}"] = (
                np.round(y_pred / 100) * 100).astype(int)
        else:
            for i, target in enumerate(target_names):
                results_df[f"{target}"] = (
                    np.round(y_pred[:, i] / 100) * 100).astype(int)

    # Add reference median from salaries.csv
    salaries_df = pd.read_csv("resources/salaries.csv")

    # Build title-to-median lookup dictionary
    title_to_median = {
        str(row["title"]).strip(): row["median"]
        for _, row in salaries_df.iterrows()
    }

    # Apply to results_df
    results_df["base_salary"] = results_df["title"].apply(
        lambda x: get_reference_median(x, title_to_median)
    )

    # Compute difference between predicted and base salary
    results_df["deviation"] = results_df["median"] - results_df["base_salary"]

    # Define adjustment factors
    state_factors = {
        "SH": 0.972222, "HH": 1.155556, "HB": 1.061111, "NI": 0.994444,
        "NW": 1.05, "RP": 1.005556, "SL": 0.988889, "BW": 1.116667,
        "MV": 0.877778, "BB": 0.911111, "BE": 1.072222, "ST": 0.883333,
        "SN": 0.905556, "TH": 0.894444, "HE": 1.116667, "BY": 1.111111
    }

    job_level_factors = {
        "junior": 0.89,
        "mid": 0.97,
        "senior": 1.10
    }

    # Compute region- and level-adjusted salary baseline
    results_df["factor_based_salary"] = results_df.apply(
        lambda row: adjusted_base(row, state_factors, job_level_factors), axis=1
    )

    # Step 10: Save the final predictions
    results_df.to_csv(output_file_name, index=False)
    print(f"✅ Predictions written to {output_file_name}")


# Entry point
if __name__ == "__main__":
    main()
