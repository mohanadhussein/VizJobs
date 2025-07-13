import argparse
from jobspy import scrape_jobs
import csv
import requests
import pandas as pd


# constants
BASE_URL = 'https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs'
BASE_SITES = ["indeed", "linkedin", "google"]
COUNTRY = "Germany"
COUNTRY_DE = "Deutschland"
UNIFIED_JOB_TYPES = ["fulltime", "parttime", "internship", "contract", "nightshift_weekend", "remote", "minijob"]
CONTRACT = "1;2"
TIMEOUT_SEC = 180
ERROR_WARNING = 2
KM_TO_MILES = 0.6214
COL_NAMES_JOBSPY = ["id", "site", "job_url", "job_url_direct", "title", "company", "location", "city", "state", 
                    "date_posted", "job_type","is_remote", "job_level", "job_function", "listing_type", "emails", 
                    "description", "company_industry", "company_url"]

COL_NAMES_API = {"beruf":"profession", "titel":"title", "refnr":"id", "arbeitgeber":"company","aktuelleVeroeffentlichungsdatum":"date_posted", 
                 "job_type":"job_type", "arbeitsort.ort":"workplace_city", "arbeitsort.region":"workplace_region", "arbeitsort.land":"location", 
                 "arbeitsort.koordinaten.lat":"workplace_lat", "arbeitsort.koordinaten.lon":"workplace_long"}

GERMAN_STATES = {
    'BW': ['Baden-Württemberg', 'Baden-Wurttemberg', 'BW'],
    'BY': ['Bayern', 'Bavaria', 'BY'],
    'BE': ['Berlin', 'Berlin', 'BE'],
    'BB': ['Brandenburg', 'Brandenburg', 'BB'],
    'HB': ['Bremen', 'Bremen', 'HB'],
    'HH': ['Hamburg', 'Hamburg', 'HH'],
    'HE': ['Hessen', 'Hesse', 'HE'],
    'MV': ['Mecklenburg-Vorpommern', 'Mecklenburg-Vorpommern', 'MV'], 
    'NI': ['Niedersachsen', 'Lower Saxony', 'NI'],
    'NW': ['Nordrhein-Westfalen', 'North Rhine-Westphalia', 'NW'],
    'RP': ['Rheinland-Pfalz', 'Rhineland-Palatinate', 'RP'],
    'SL': ['Saarland', 'Saarland', 'SL'],
    'SN': ['Sachsen', 'Saxony', 'SN'],
    'ST': ['Sachsen-Anhalt', 'Saxony-Anhalt', 'ST'],
    'SH': ['Schleswig-Holstein', 'Schleswig-Holstein', 'SH'],
    'TH': ['Thüringen', 'Thuringia', 'TH']
}

## Defining functions needed in the script and for cleaning outputs
# state corrector
def state_corrector(state_name, state_dict):
    """Corrects state names to their corresponding letter code"""
    for letter_code, name_variants in state_dict.items():
        if state_name in name_variants:
            return letter_code
        
# Job level corrector
def determine_job_level(df):
    """Corrects job level based on job title and job level"""
    # Define keywords for each level
    level_definitions = {
        "lead": ["ceo", "cto", "cfo", "coo", "vp", "president", "director",
                  "executive", "head", "chief", "founder", "manager"],
        "senior": ["senior", "principal", "staff", "expert", "sr", "distinguished", 
                   "consultant"],
        "junior": ["junior", "entry", "associate", "graduate", "grad",
                   "trainee", "intern"],
        "mid": ["mid", "intermediate", "experienced", "regular", "professional"]
    }
    # combine title and job_level into a single lowercase string
    title = str(df['title']).lower()
    level_col = str(df['job_level']).lower()
    combined_text = title + " " + level_col

    # iterate through dictionary and map level
    for level, keywords in level_definitions.items():
        # For each level, iterate through its specific keywords
        for kw in keywords:
            if kw in combined_text:
                return level
            
    return 'mid'

# argument parser
def create_parser():
    """Create and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="Job search CLI tool for Germany from German Federal Employment Agency and Job websites (indeed, linkedin, google)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="Usage example: python3 VizJobs.py -J 'Software Engineer' -C 'Berlin'"
    )

    # mandatory arguments
    parser.add_argument("-J", "--job-Title", 
                       help="A title to find jobs for, see list of recommended search terms in job_list.txt file",
                       required=True, type=str, metavar="[TITLE]")

    # optional arguments
    parser.add_argument("-C","--city",
                       help="A city within Germany to find jobs in, choosing a large city allows for more options. Default is empty string",
                       required=False, type=str, default="", metavar="CITY")

    parser.add_argument("-D", "--distance",
                       help="Distance in km to search for jobs within respective to the given city. Default is empty string",
                       required=False, type=int, default=100, metavar="DISTANCE")

    parser.add_argument("-R", "--results", 
                       help="Maximum number of results to be displayed from each source", 
                       required=False, type=int, default=20, metavar="RESULTS")

    parser.add_argument("-H", "--hours-old",
                       help="The oldest job to be found, in hours",
                       required=False, type=int, default=168, metavar="HOURS")

    parser.add_argument("-T", "--job-type",
                       help=f"The type of employment to be searched for. Options are {UNIFIED_JOB_TYPES}",
                       required=False, type=str, default="fulltime")

    parser.add_argument("-O", "--output",
                       help=f"A csv file name to save the job search output.",
                       required=False, type=str, default="combined_job_search.csv")

    # jobspy specific arguments
    parser.add_argument("--proxies",
                       help="List of proxy servers to use for requests. In format ['user:pass@host:port', 'localhost']",
                       required=False, default="localhost", type=str, nargs="+")

    parser.add_argument("--google_search_term", 
                       help="Text input for google search. By default a combination of JOB_TITLE and CITY is used internally",
                       required=False, default="", type=str)

    parser.add_argument("--proxy_ca_cert", 
                       help="Path for CA certificate for proxies. Default is empty string",
                       required=False, default=None, type=str)

    # API specific arguments
    parser.add_argument("--employment_type",
                       help="Indicates the type of the employment. Options are: 'work', 'self_employment', 'dual_study', 'training'",
                       required=False, default="work", type=str)

    parser.add_argument("--private_agencies", 
                       help="Include jobs from private employment agencies. Adding the flag itself is enough to include them",
                       required=False, default="true")

    return parser

def run_jobspy(job_title, city, distance, results, hours_old, job_type, google_search_term, proxies, ca_certificate):
    """Run JobSpy scraping and return cleaned results."""
    # Mapping job_type for JobSpy
    JOBSPY_JOB_TYPE_MAPPING = {
        "fulltime": "fulltime",
        "parttime": "parttime",
        "internship": "internship", 
        "contract": "contract",
    }
    
    mapped_job_type_jobspy = job_type if job_type in JOBSPY_JOB_TYPE_MAPPING.keys() else "fulltime"
    
    print(f"🔍 Scraping jobs from {BASE_SITES} for '{job_title}' in {COUNTRY}...")

    jobspy_output = scrape_jobs(
        site_name=BASE_SITES,
        search_term=job_title,
        google_search_term=google_search_term,
        location=COUNTRY,
        distance=int(distance * KM_TO_MILES),
        job_type=mapped_job_type_jobspy,
        proxies=proxies,
        results_wanted=results,
        description_format="markdown",
        hours_old=hours_old,
        verbose=ERROR_WARNING,
        linkedin_fetch_description=True,
        country_indeed=COUNTRY,
        ca_cert=ca_certificate
    )

    print(f"✅ JobSpy completed - Found {len(jobspy_output) if jobspy_output is not None else 0} jobs")

    if jobspy_output is not None and not jobspy_output.empty:
        # Clean city and state data
        jobspy_output["city"] = jobspy_output["location"].str.strip().str.split(",", expand=True)[0]
        jobspy_output["state"] = jobspy_output["location"].str.strip().str.split(",", expand=True)[1]
        jobspy_output["state"] = jobspy_output["state"].str.strip()
        jobspy_output["state"] = jobspy_output["state"].map(lambda x: state_corrector(x, GERMAN_STATES))

        # Correct state names if needed
        for letter_code, name_variants in GERMAN_STATES.items():
            for i in range(len(jobspy_output["city"])):
                if jobspy_output["city"][i] in name_variants:
                    jobspy_output.loc[i, "state"] = letter_code

        jobspy_output_clean = jobspy_output[COL_NAMES_JOBSPY]
        jobspy_output_clean.to_csv("jobspy_output_clean.csv", index=False, encoding='utf-8-sig')
        print(f"✅ Cleaned and saved JobSpy results to: jobspy_output_clean.csv")
        return jobspy_output_clean
    
    return pd.DataFrame()

def run_federal_agency_api(job_title, city, distance, results, hours_old, job_type, employment_type, private_agencies):
    """Run Federal Agency API request and return cleaned results."""
    # Mapping job_type for API
    API_JOB_TYPE_MAPPING = {
        "fulltime": "vz",
        "parttime": "tz", 
        "nightshift_weekend": "snw",
        "remote": "ho",
        "minijob": "mj"
    }
    
    # Mapping offer_type for API tool
    API_EMPLOYMENT_TYPE_MAPPING = {
        "work": 1,
        "self_employment": 2,
        "dual_study": 4,
        "training": 34
    }
    
    mapped_job_type_API = API_JOB_TYPE_MAPPING[job_type] if job_type in API_JOB_TYPE_MAPPING.keys() else "vz"
    mapped_employment_type_API = API_EMPLOYMENT_TYPE_MAPPING[employment_type]
    
    headers = {"X-API-key":"jobboerse-jobsuche"}
    params = {
        "was": job_title,
        "wo": city if city else COUNTRY_DE,
        "size": results,
        "veroeffentlichtseit": int(hours_old/24) if hours_old/24 > 1 else 1,
        "pav": private_agencies,
        "angebotsart": mapped_employment_type_API,
        "befristung": CONTRACT,
        "umkreis": distance, 
        "arbeitszeit": mapped_job_type_API,
    }

    print("🌐 Fetching jobs from Federal Employment Agency ...")

    try:
        print("sending API request...")
        response = requests.get(BASE_URL, headers=headers, params=params, timeout=TIMEOUT_SEC)
        response.raise_for_status()
        api_output = response.json()
        print(f"✅ Successfully terminated. Fetched data for {len(api_output['stellenangebote']) if 'stellenangebote' in api_output else 0} job/s from Federal Employment Agency")
        
        if "stellenangebote" in api_output:
            api_output_jobs_norm = pd.json_normalize(api_output["stellenangebote"])
            api_output_jobs_norm["job_type"] = mapped_job_type_API
            api_output_jobs_clean = api_output_jobs_norm[COL_NAMES_API.keys()]
            api_output_jobs_clean.columns = COL_NAMES_API.values()
            api_output_jobs_clean.to_csv("api_output_clean.csv", index=False)
            print(f"✅ Cleaned and saved API results to api_output_jobs_clean.csv")
            return api_output_jobs_clean
        else:
            print("❗ No results found from Federal Agency API")
            return pd.DataFrame()
            
    except requests.exceptions.Timeout:
        print("❌ Federal Agency API request timed out")
    except requests.exceptions.ConnectionError:
        print("❌ Federal Agency API connection failed")
    except requests.exceptions.HTTPError as error1:
        print(f"❌ Federal Agency API HTTP error: {error1.response.status_code}")
    except requests.exceptions.RequestException as error2:
        print(f"❌ Federal Agency API error: {error2}")
    
    return pd.DataFrame()

def save_combined_results(jobspy_output_clean, api_output_jobs_clean, output_file):
    """Save combined results to CSV file."""
    if not jobspy_output_clean.empty and not api_output_jobs_clean.empty:
        combined_output = pd.concat([jobspy_output_clean, api_output_jobs_clean], ignore_index=True)
        combined_output['title'] = combined_output['title'].str.replace(r'\s*\(.*?\)\s*|\s*\[.*?\]\s*', ' ', regex=True)
        combined_output['title'] = combined_output['title'].str.replace(r':in\b', '', regex=True)
        combined_output['title'] = combined_output['title'].str.replace(r'[^a-zA-Z0-9]+', ' ', regex=True)
        combined_output['title'] = combined_output['title'].str.strip()
        combined_output["correct_job_level"] = combined_output.apply(determine_job_level, axis=1)
        combined_output.to_csv(output_file, index=False)
        print(f"✅ Results from JobSpy and API saved to {output_file}")
    elif not jobspy_output_clean.empty:
        jobspy_output_clean.to_csv(output_file, index=False)
        print(f"✅ Results from JobSpy saved to {output_file}")
    elif not api_output_jobs_clean.empty:
        api_output_jobs_clean.to_csv(output_file, index=False)
        print(f"✅ Results from Federal Agency API saved to {output_file}")

def main():
    """Main function to run the job search tool."""
    parser = create_parser()
    args = parser.parse_args()

    # Parse arguments
    job_title = args.job_Title
    city = args.city
    distance = args.distance
    results = args.results
    hours_old = args.hours_old
    job_type = args.job_type
    output_file = args.output
    
    # JobSpy specific arguments
    google_search_term = args.google_search_term if args.google_search_term else f"{job_title} in {city}, {COUNTRY}"
    proxies = args.proxies
    ca_certificate = args.proxy_ca_cert
    
    # API specific arguments
    private_agencies = args.private_agencies
    employment_type = args.employment_type

    # Run JobSpy
    jobspy_results = run_jobspy(job_title, city, distance, results, hours_old, job_type, 
                               google_search_term, proxies, ca_certificate)

    # Run Federal Agency API
    api_results = run_federal_agency_api(job_title, city, distance, results, hours_old, 
                                        job_type, employment_type, private_agencies)

    # Save combined results
    save_combined_results(jobspy_results, api_results, output_file)

    print("✅ VizJobs completed.")

if __name__ == "__main__":
    main()