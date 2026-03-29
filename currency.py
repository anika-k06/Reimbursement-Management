import requests

# ─── Constants ────────────────────────────────────────────────────────────────

# This is the API your problem statement gave us
# Replace {BASE_CURRENCY} with any currency code like "USD", "INR", "EUR"
# Example: https://api.exchangerate-api.com/v4/latest/USD
# Returns: { "base": "USD", "rates": { "INR": 83.5, "EUR": 0.91, ... } }

EXCHANGE_RATE_API = "https://api.exchangerate-api.com/v4/latest/{}"


# ─── Main Functions ───────────────────────────────────────────────────────────

def get_exchange_rates(base_currency: str) -> dict:
    """
    Fetch all exchange rates for a given base currency.

    Example:
        get_exchange_rates("USD")
        → { "INR": 83.5, "EUR": 0.91, "GBP": 0.79, ... }

    Returns empty dict if the API call fails.
    """
    try:
        url      = EXCHANGE_RATE_API.format(base_currency.upper())
        response = requests.get(url, timeout=5)  # timeout after 5 seconds
        data     = response.json()
        return data.get("rates", {})

    except Exception as e:
        # If API is down or network fails, return empty dict
        # The calling code must handle this gracefully
        print(f"[currency.py] Failed to fetch rates for {base_currency}: {e}")
        return {}


def convert_amount(amount: float, from_currency: str, to_currency: str) -> float | None:
    """
    Convert an amount from one currency to another.

    Example:
        convert_amount(50, "USD", "INR")
        → 4175.0   (if 1 USD = 83.5 INR)

    Returns None if conversion fails (API down, invalid currency code, etc.)

    How it works:
        Step 1 — fetch all rates with from_currency as base
                 e.g. base = USD → { INR: 83.5, EUR: 0.91, ... }
        Step 2 — look up the to_currency in those rates
                 e.g. rates["INR"] = 83.5
        Step 3 — multiply: 50 USD × 83.5 = 4175.0 INR
    """
    # If both currencies are the same, no conversion needed
    if from_currency.upper() == to_currency.upper():
        return round(amount, 2)

    rates = get_exchange_rates(from_currency)

    if not rates:
        # API call failed
        return None

    rate = rates.get(to_currency.upper())

    if rate is None:
        # Currency code not found in rates (e.g. typo like "USDD")
        print(f"[currency.py] Currency '{to_currency}' not found in rates.")
        return None

    converted = amount * rate
    return round(converted, 2)  # round to 2 decimal places


def get_all_countries_currencies() -> list:
    """
    Fetch all countries and their currencies from the REST Countries API.
    Used on the signup page so the user can pick their country
    and the company currency gets set automatically.

    API: https://restcountries.com/v3.1/all?fields=name,currencies

    Returns a list of dicts like:
    [
        { "country": "India", "currency_code": "INR", "currency_name": "Indian Rupee" },
        { "country": "United States", "currency_code": "USD", "currency_name": "US Dollar" },
        ...
    ]

    Returns empty list if the API call fails.
    """
    try:
        url      = "https://restcountries.com/v3.1/all?fields=name,currencies"
        response = requests.get(url, timeout=10)
        data     = response.json()

        result = []

        for country in data:
            country_name = country.get("name", {}).get("common", "Unknown")
            currencies   = country.get("currencies", {})

            # A country can have multiple currencies — we take the first one
            for code, info in currencies.items():
                result.append({
                    "country":       country_name,
                    "currency_code": code,                        # e.g. "INR"
                    "currency_name": info.get("name", "Unknown")  # e.g. "Indian Rupee"
                })
                break  # only take first currency per country

        # Sort alphabetically by country name for the dropdown
        result.sort(key=lambda x: x["country"])
        return result

    except Exception as e:
        print(f"[currency.py] Failed to fetch countries/currencies: {e}")
        return []


# ─── Helper used by expenses route ───────────────────────────────────────────

def fill_base_amount(expense, company_currency: str) -> bool:
    """
    Convert the expense amount into the company's base currency
    and save it into expense.amount_in_base.

    This is called in routes/expenses.py right before saving a new expense.

    Example:
        expense.amount   = 50.0
        expense.currency = "USD"
        company_currency = "INR"
        → expense.amount_in_base = 4175.0

    Returns True if successful, False if conversion failed.

    Usage in expenses route:
        success = fill_base_amount(expense, current_user.company.currency_code)
        if not success:
            return error response
    """
    converted = convert_amount(expense.amount, expense.currency, company_currency)

    if converted is None:
        return False  # caller should handle this — show error to user

    expense.amount_in_base = converted
    return True
