from config.utils import log
from data_sources.census_loader import download_census_income, validate_inputs
from data_sources.market_file_updater import refresh_market_files


def main():
    log("Starting Housing Predictor V10 Data Update...\n")

    log("Refreshing Zillow and Realtor market files...")
    refresh_market_files()

    log("\nRefreshing Census affordability data...")
    download_census_income()

    log("\nValidating installed inputs...")
    validate_inputs()

    log("\nData update complete.")
    log("Next step: python run_forecast.py")


if __name__ == "__main__":
    main()