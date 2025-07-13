# --- Import standard and third-party libraries ---
from pathlib import Path
import streamlit as st  # Web app framework
import pandas as pd  # DataFrame handling
import geopandas as gpd  # Geospatial data processing
import numpy as np  # Numerical computations
import folium  # Interactive maps
import branca.colormap as bcm  # Color maps for folium
from streamlit_folium import st_folium  # Embedding folium maps in Streamlit
from datetime import datetime  # Time and date handling
import streamlit.components.v1 as components  # HTML injection
import matplotlib.pyplot as plt  # Plotting
import matplotlib.ticker as ticker  # Tick formatting for axes
import io
import os
import argparse  # Argument parsing from CLI

# --- Helper function for custom rounding behavior ---
def round_half_up(n):
    """Rounds a number to the nearest integer, with .5 rounding up."""
    return int(np.floor(n + 0.5))


# --- Main application entry point ---
def main():
    # --- Parse input argument (CSV file with predictions) ---
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "-I", "--input",
        help="The input file with the required columns. See README for details.",
        required=True,
        type=str,
        default="combined_job_search_predictions.csv"
    )
    args = parser.parse_args()
    input_file_name = args.input

    # --- Streamlit UI setup ---
    st.set_page_config(layout="wide")
    st.title("VizJobs – A German Job & Salary Visualization Tool")
    st.subheader("Map of Your Scrapped Jobs")

    # --- Load job data and rename key columns ---
    df = pd.read_csv(input_file_name, encoding="utf-8")
    df.rename(columns={
        "median": "predicted_salary",
        "base_salary": "median_germany_all_factors",
        "factor_based_salary": "germany_median_times_factors"
    }, inplace=True)

    # --- Load geospatial data for German states (GeoJSON) ---
    geojson_url = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/1_sehr_hoch.geo.json"
    gdf = gpd.read_file(geojson_url)
    gdf = gdf.rename(columns={"name": "state_name"})

    # --- Map state abbreviations to full state names ---
    state_mapping = {
        "BW": "Baden-Württemberg", "BY": "Bayern", "BE": "Berlin", "BB": "Brandenburg",
        "HB": "Bremen", "HH": "Hamburg", "HE": "Hessen", "MV": "Mecklenburg-Vorpommern",
        "NI": "Niedersachsen", "NW": "Nordrhein-Westfalen", "RP": "Rheinland-Pfalz",
        "SL": "Saarland", "SN": "Sachsen", "ST": "Sachsen-Anhalt",
        "SH": "Schleswig-Holstein", "TH": "Thüringen"
    }
    df["state_name"] = df["state"].map(state_mapping).fillna("N/A")

    # --- Preprocessing: date conversion, salary cleaning, job age calculation ---
    heute = pd.to_datetime(datetime.today().date())
    df["date_posted"] = pd.to_datetime(df["date_posted"], errors="coerce")
    df["Posting Age (days)"] = (heute - df["date_posted"]).dt.days
    df["predicted_salary"] = pd.to_numeric(df["predicted_salary"], errors="coerce")

    # --- Aggregate job counts and average salaries per state ---
    job_counts = df["state_name"].value_counts().to_dict()
    avg_salary = df.groupby("state_name")["predicted_salary"].mean().round(0).to_dict()
    gdf["job_count"] = gdf["state_name"].map(job_counts).fillna(0).astype(int)
    gdf["avg_salary"] = gdf["state_name"].map(avg_salary).fillna(0).astype(int)

    # --- UI: state selection ---
    bundeslaender = sorted([x for x in df["state_name"].dropna().unique() if x != "N/A"])
    selection_options = ["All States"] + bundeslaender
    if "selected_state" not in st.session_state:
        st.session_state["selected_state"] = "All States"
    selected_state = st.session_state["selected_state"]

    # --- UI: choose map type ---
    mode = st.radio("Choose a map:", ["Number of Jobs per State", "Predicted ∅ Annual Salary per State (€)"], horizontal=True)
    st.markdown("*Note: Job postings without state information are not shown on the map.*")

    # --- Dynamic color scale depending on map mode ---
    if mode == "Number of Jobs per State":
        data_col = "job_count"
        values = df["state_name"].map(job_counts)
        vmin, vmax = int(values.min()), int(values.max())
        step = max(1, round_half_up((vmax - vmin) / 5))
        ticks = list(range(vmin, vmax + step, step))
        colorscale = bcm.LinearColormap(["#c6dbef", "#4292c6", "#084594"], vmin=vmin, vmax=vmax).to_step(index=ticks)
    else:
        data_col = "avg_salary"
        values = df["predicted_salary"]
        vmin, vmax = int(values.min()), int(values.max())
        step = max(1000, round_half_up((vmax - vmin) / 5 / 1000) * 1000)
        ticks = list(range(vmin, vmax + step, step))
        colorscale = bcm.LinearColormap(["#ccece6", "#238b45", "#00441b"], vmin=vmin, vmax=vmax).to_step(index=ticks)
    colorscale.caption = data_col

    # --- Helper function to convert values to colors ---
    def get_color(value):
        if pd.isna(value) or value == 0:
            return "#dddddd"
        return colorscale(value)

    # --- Build interactive folium map ---
    m = folium.Map(location=[51.1657, 10.4515], zoom_start=6.3, tiles="cartodbpositron")
    for _, row in gdf.iterrows():
        tooltip = f"{row['state_name']}<br>"
        tooltip += f"Number of Jobs: {row['job_count']}" if mode == "Number of Jobs per State" else f"∅ Predicted Salary: {row['avg_salary']} €"
        fill_color = get_color(row[data_col])
        folium.GeoJson(
            row["geometry"],
            tooltip=tooltip,
            style_function=lambda x, fc=fill_color: {
                "fillColor": fc,
                "color": "black",
                "weight": 1,
                "fillOpacity": 0.7
            }
        ).add_to(m)

    # --- Optional: highlight selected state in red outline ---
    if selected_state != "All States":
        selected_geometry = gdf[gdf["state_name"] == selected_state].iloc[0]["geometry"]
        folium.GeoJson(
            selected_geometry,
            style_function=lambda x: {
                "fillColor": "none",
                "color": "red",
                "weight": 4,
                "fillOpacity": 0
            }
        ).add_to(m)

    # --- Show the final map in the Streamlit app ---
    colorscale.add_to(m)
    components.html(m._repr_html_(), height=600)

    # --- UI: Select state and sorting method ---
    st.markdown("### Job Details")
    selected_state = st.selectbox("Choose a state:", selection_options, index=selection_options.index(st.session_state["selected_state"]), key="selected_state")

    sort_labels = {
        "Posting Age → new to old": "📅 Posting Age → new to old",
        "Posting Age → old to new": "📅 Posting Age → old to new",
        "Salary → high to low": "💰 Salary (ML-predicted) → high to low",
        "Salary → low to high": "💰 Salary (ML-predicted) → low to high"
    }
    sort_option_display = st.selectbox("Sort job list by:", list(sort_labels.values()))
    sort_option = [k for k, v in sort_labels.items() if v == sort_option_display][0]

    # --- Table columns and renaming ---
    display_columns = ["title", "correct_job_level", "predicted_salary", "germany_median_times_factors", "median_germany_all_factors", "job_url", "company", "city", "state_name", "date_posted", "Posting Age (days)"]
    rename_columns = {
        "title": "Job Title",
        "correct_job_level": "Job Level",
        "predicted_salary": "ML-PREDICTED SALARY (€)",
        "median_germany_all_factors": "GERMANY-WIDE MEDIAN (€)",
        "germany_median_times_factors": "FACTOR-BASED SALARY (€)",
        "job_url": "Link to Job Posting",
        "company": "Company",
        "city": "City",
        "state_name": "State",
        "date_posted": "Date Posted"
    }
    filtered = df[display_columns] if selected_state == "All States" else df[df["state_name"] == selected_state][display_columns]
    filtered = filtered.rename(columns=rename_columns)

    # --- Format missing values and numerical columns ---
    filtered["Date Posted"] = filtered["Date Posted"].apply(lambda x: x.date().isoformat() if pd.notnull(x) else "N/A")
    for col in ["ML-PREDICTED SALARY (€)", "FACTOR-BASED SALARY (€)", "GERMANY-WIDE MEDIAN (€)"]:
        filtered[col] = filtered[col].apply(lambda x: f"{int(x):,}".replace(",", ".") if pd.notnull(x) else "N/A")
    filtered["Posting Age (days)"] = filtered["Posting Age (days)"].apply(lambda x: f"{int(x)}" if pd.notnull(x) else "N/A")
    filtered["Link to Job Posting"] = filtered["Link to Job Posting"].apply(lambda url: f'<a href="{url}" target="_blank">{url}</a>' if pd.notnull(url) else "N/A")
    for col in ["Job Title", "Job Level", "Company", "City", "State", "Date Posted"]:
        filtered[col] = filtered[col].fillna("N/A")

    # --- Sort data based on selection ---
    sort_column_map = {
        "Posting Age → new to old": ("Posting Age (days)", True),
        "Posting Age → old to new": ("Posting Age (days)", False),
        "Salary → high to low": ("ML-PREDICTED SALARY (€)", False),
        "Salary → low to high": ("ML-PREDICTED SALARY (€)", True)
    }
    sort_col, ascending = sort_column_map[sort_option]
    filtered["_sort"] = pd.to_numeric(filtered[sort_col].str.replace(".", "", regex=False), errors="coerce")
    filtered = filtered.sort_values(by="_sort", ascending=ascending).drop(columns="_sort")

    # --- Display the job table ---
    st.markdown(f"<div style='max-width: 100%; overflow-x: auto;'>{filtered.to_html(escape=False, index=False)}</div>", unsafe_allow_html=True)

    # --- Plot 1: Job Posting Trend (Daily/Monthly) ---
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 📈 Job Posting Trend")
        interval_option = st.radio("Choose interval:", ["Daily", "Monthly"], horizontal=True)
        if interval_option == "Daily":
            counts = df["date_posted"].dt.date.value_counts().sort_index()
            x_labels = [d.strftime("%d.%m") for d in counts.index]
            title = "Number of Job Postings per Day"
        else:
            counts = df["date_posted"].dt.to_period("M").value_counts().sort_index()
            x_labels = [p.strftime("%b %Y") for p in counts.index]
            title = "Number of Job Postings per Month"
        fig1, ax1 = plt.subplots()
        counts.plot(kind="bar", ax=ax1, color="#6baed6")
        ax1.set_title(title)
        ax1.set_xlabel("Date" if interval_option == "Daily" else "Month")
        ax1.set_ylabel("Number of Postings")
        ax1.set_xticklabels(x_labels, rotation=45, ha="right")
        ax1.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        ax1.yaxis.grid(True)
        ax1.xaxis.grid(False)
        st.pyplot(fig1)

    # --- Plot 2: Salary Deviation ---
    with col2:
        st.markdown("#### 📉 Deviation of ML-Predicted Salary")
        deviation_choice = st.radio("Choose comparison basis:", ["Factor-Based Salary", "Germany-Wide Median"], horizontal=True, key="deviation_radio")
        df["diff_ml_vs_factor"] = df["predicted_salary"] - df["germany_median_times_factors"]
        df["diff_ml_vs_median"] = df["predicted_salary"] - df["median_germany_all_factors"]
        df_diff = df[["diff_ml_vs_factor", "diff_ml_vs_median"]].dropna()
        fig2, ax2 = plt.subplots()
        bins = np.arange(-20000, 20000 + 1000, 1000)
        if deviation_choice == "Factor-Based Salary":
            ax2.hist(df_diff["diff_ml_vs_factor"], bins=bins, alpha=0.7, color="#3182bd")
            ax2.set_title("Deviation: ML vs. Factor-Based Salary")
        else:
            ax2.hist(df_diff["diff_ml_vs_median"], bins=bins, alpha=0.7, color="#e6550d")
            ax2.set_title("Deviation: ML vs. Germany-Wide Median")
        ax2.axvline(0, color="black", linestyle="--", linewidth=1)
        ax2.set_xlabel("Deviation in €")
        ax2.set_ylabel("Number of Jobs")
        ax2.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        ax2.grid(True)
        st.pyplot(fig2)

    # --- Plot 3: Job Level Distribution (Pie Chart) ---
    col3, col4 = st.columns(2)
    with col3:
        st.markdown("#### 📊 Ratio of Job levels")
        df["correct_job_level"] = df["correct_job_level"].fillna("n/a")
        job_level_counts = df["correct_job_level"].value_counts()
        avg_salaries_per_level = df.groupby("correct_job_level")["predicted_salary"].mean().round(0).astype("Int64")
        fig_pie, ax_pie = plt.subplots()
        ax_pie.pie(job_level_counts, labels=job_level_counts.index, autopct="%1.1f%%", startangle=140)
        ax_pie.axis("equal")
        st.pyplot(fig_pie)
        st.markdown("**Average ML-Predicted Salary per Job Level:**")
        ordered_levels = ["lead", "senior", "mid", "junior", "n/a"]
        for level in ordered_levels:
            if level in avg_salaries_per_level:
                salary = avg_salaries_per_level[level]
                salary_display = f"{salary:,}".replace(",", ".") + " €" if pd.notnull(salary) else "N/A"
                st.markdown(f"- **{level}**: {salary_display}")

    # --- Plot 4: Salary per Company (Bar Chart) ---
    with col4:
        st.markdown("#### 📊 ∅ ML-Predicted Salary per Company")
        salary_per_company = df[["company", "predicted_salary"]].dropna()
        salary_mean_sorted = salary_per_company.groupby("company")["predicted_salary"].mean().sort_values()
        fig_bar, ax_bar = plt.subplots(figsize=(6, max(4, len(salary_mean_sorted) * 0.3)))
        salary_mean_sorted.plot(kind="barh", ax=ax_bar, color="#9ecae1")
        ax_bar.set_ylabel("")
        ax_bar.set_xlabel("Predicted Salary (€)")
        st.pyplot(fig_bar)

    # --- Download section: Save all generated plots as image files ---
    st.markdown("---")
    st.markdown("### 📥 Save All Plots")
    if st.button("💾 Save plots"):
        base_dir = Path(__file__).resolve().parent / "viz_plots"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        subfolder = os.path.join(base_dir, timestamp)
        os.makedirs(subfolder, exist_ok=True)

        # Save all plots
        fig1.savefig(os.path.join(subfolder, "number_jobs_postings.png"), bbox_inches="tight")
        fig2.savefig(os.path.join(subfolder, "deviation_ML_predicted.png"), bbox_inches="tight")
        fig_pie.savefig(os.path.join(subfolder, "job_level_distribution.png"), bbox_inches="tight")
        fig_bar.savefig(os.path.join(subfolder, "avg_salary_per_company.png"), bbox_inches="tight")

        # Confirmation message
        st.success("✅ Plots saved!")
        st.markdown("**Saved files:**")
        st.markdown(f"- `number_jobs_postings.png`")
        st.markdown(f"- `deviation_ML_predicted.png`")
        st.markdown(f"- `job_level_distribution.png`")
        st.markdown(f"- `avg_salary_per_company.png`")
        st.info(f"📁 Path: `{subfolder}`")

# --- Only run the app if the script is executed directly ---
if __name__ == "__main__":
    main()
