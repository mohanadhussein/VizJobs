import pandas as pd
import sklearn
import joblib
import matplotlib.pyplot as plt

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import OneHotEncoder, PolynomialFeatures
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LinearRegression

def print_predictions(model, new_job, target_columns):
    predicted_salary = model.predict(new_job)
    print("Predicted salary with Polynomial Regression:")
    for i, target in enumerate(target_columns):
        print(f"{target}: {predicted_salary[0][i]:.2f}")

# Plot all actual vs predicted values in one scatter plot
def plot_combined_scatter(y_test, predictions_poly):
    plt.figure(figsize=(8, 6))
    plt.scatter(y_test.values.flatten(), predictions_poly.flatten(), alpha=0.5, color='yellow')
    plt.plot(
        [y_test.values.min(), y_test.values.max()],
        [y_test.values.min(), y_test.values.max()],
        '--r', linewidth=2
    )
    plt.xlabel("Actual Salary")
    plt.ylabel("Predicted Salary")
    plt.title("Actual vs Predicted Salary (Combined)")
    plt.grid(True)
    plt.tight_layout()
    plt.show()

# Dynamically plot each target column: actual vs predicted
def plot_predictions(y_test, predictions_poly, target_columns):
    
    plt.figure(figsize=(8, 6))
    for i, target in enumerate(target_columns):
        plt.scatter(
            y_test[target],
            predictions_poly[:, i],
            alpha=0.5,
            label=f'Predicted {target} (Poly Deg2)'
        )

    # Plot a diagonal reference line (perfect prediction)
    plt.plot(
        [y_test[target_columns[0]].min(), y_test[target_columns[0]].max()],
        [y_test[target_columns[0]].min(), y_test[target_columns[0]].max()],
        '--r', linewidth=2
    )

    plt.xlabel("Actual Salary")
    plt.ylabel("Predicted Salary")
    plt.title("Actual vs Predicted Salary")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()


def main():
    # Load dataset
    df = pd.read_csv("salaries.csv")

    # Features and target
    X = df[['title', 'company_industry', 'correct_job_level', 'state']]
    y = df[['p10', 'median', 'p90']]

    # Preprocess categorical features
    categorical_features = ['title', 'company_industry', 'correct_job_level', 'state']
    preprocessor = ColumnTransformer([
        ('onehot', OneHotEncoder(handle_unknown='ignore'), categorical_features)
    ])

    # Polynomial regression pipeline
    degree = 2
    poly_model = Pipeline([
        ('preprocessor', preprocessor),
        ('poly_features', PolynomialFeatures(degree, include_bias=False)),
        ('regressor', LinearRegression())
    ])

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # Train the model
    poly_model.fit(X_train, y_train)

    # Predict and evaluate
    try:
        predictions_poly = poly_model.predict(X_test)
    except ValueError as e:
        print("Prediction error:", e)
        return

    # Save the trained model
    joblib.dump(poly_model, "salary_predictor.pkl")

    target_columns = y.columns.tolist()

    # Visualizations
    plot_combined_scatter(y_test, predictions_poly)
    plot_predictions(y_test, predictions_poly, target_columns)


# Entry point
if __name__ == "__main__":
    main()
