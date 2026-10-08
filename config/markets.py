NATIONAL_SERIES = {
    "mortgage_30yr": "MORTGAGE30US",
    "ten_year": "DGS10",
    "fed_funds": "FEDFUNDS",
    "cpi": "CPIAUCSL",
    "national_unemployment": "UNRATE",
    "national_payrolls": "PAYEMS",
    "consumer_sentiment": "UMCSENT",
    "housing_starts": "HOUST",
    "building_permits": "PERMIT",
    "months_supply": "MSACSR",
    "new_home_sales": "HSN1F",
}

MARKETS = {
    "Wichita Composite": {
        "aliases": [
            "wichita", "wichita ks", "wichita, ks", "wichita metro",
            "wichita composite", "sedgwick", "sedgwick county",
            "sedgwick county, ks", "butler county", "butler county, ks",
            "harvey county", "harvey county, ks", "sumner county", "sumner county, ks",
        ],
        "metro_names": ["wichita ks"],                      # V11: exact Zillow / Realtor.com metro names
        "hpi_target_series": "ATNHPIUS48620Q",
        "metro_unemployment": "WICH620URN",
        "metro_payrolls": "WICH620NAN",
        "metro_labor_force": "WICH620LF",
        "counties": {
            "Sedgwick KS": {"fips": "20173", "use_listing_data": True},
            "Butler KS": {"fips": "20015", "use_listing_data": True},
            "Harvey KS": {"fips": "20079", "use_listing_data": False},
            "Sumner KS": {"fips": "20191", "use_listing_data": False},
        },
    },
    "DFW Composite": {
        "aliases": [
            "dfw", "dallas", "dallas tx", "dallas, tx",
            "dallas-fort worth", "dallas fort worth",
            "dallas-fort worth-arlington", "dallas-fort worth-arlington, tx",
            "dallas-plano-irving", "fort worth", "fort worth-arlington-grapevine",
            "tarrant", "collin", "denton", "rockwall", "kaufman",
            "ellis", "johnson", "parker", "wise", "hunt",
        ],
        "metro_names": ["dallas tx", "dallas fort worth arlington tx"],
        "target_components": {
            "Dallas-Plano-Irving": "ATNHPIUS19124Q",
            "Fort Worth-Arlington-Grapevine": "ATNHPIUS23104Q",
        },
        "target_component_weights": {
            "Dallas-Plano-Irving": 0.65,
            "Fort Worth-Arlington-Grapevine": 0.35,
        },
        "metro_unemployment": "DALL148UR",
        "metro_payrolls": "DALL148NAN",
        "metro_labor_force": "DALL148LF",
        "metro_building_permits": "DALL148BPPRIVSA",
        "counties": {
            "Dallas TX": {"fips": "48113", "use_listing_data": True},
            "Tarrant TX": {"fips": "48439", "use_listing_data": True},
            "Collin TX": {"fips": "48085", "use_listing_data": True},
            "Denton TX": {"fips": "48121", "use_listing_data": True},
            "Rockwall TX": {"fips": "48397", "use_listing_data": True},
            "Kaufman TX": {"fips": "48257", "use_listing_data": True},
            "Ellis TX": {"fips": "48139", "use_listing_data": True},
            "Johnson TX": {"fips": "48251", "use_listing_data": True},
            "Parker TX": {"fips": "48367", "use_listing_data": True},
            "Wise TX": {"fips": "48497", "use_listing_data": True},
            "Hunt TX": {"fips": "48231", "use_listing_data": True},
        },
    },
}