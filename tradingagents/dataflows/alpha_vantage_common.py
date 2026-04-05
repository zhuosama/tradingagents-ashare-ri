import os
import time
import logging
import requests
import pandas as pd
import json
from datetime import datetime
from io import StringIO

logger = logging.getLogger(__name__)

API_BASE_URL = "https://www.alphavantage.co/query"

# ── Timeout / retry settings ──────────────────────────────────────────────────
_DATA_API_TIMEOUT = int(os.getenv("DATA_API_TIMEOUT", "60"))   # seconds per request
_DATA_RETRY_DELAYS: tuple[int, ...] = (2, 4, 8)               # exponential backoff
_RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})


def _debug_enabled() -> bool:
    return os.getenv("TRADINGAGENTS_DEBUG", "").lower() in ("1", "true", "yes")

def get_api_key() -> str:
    """Retrieve the API key for Alpha Vantage from environment variables."""
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise ValueError("ALPHA_VANTAGE_API_KEY environment variable is not set.")
    return api_key

def format_datetime_for_api(date_input) -> str:
    """Convert various date formats to YYYYMMDDTHHMM format required by Alpha Vantage API."""
    if isinstance(date_input, str):
        # If already in correct format, return as-is
        if len(date_input) == 13 and 'T' in date_input:
            return date_input
        # Try to parse common date formats
        try:
            dt = datetime.strptime(date_input, "%Y-%m-%d")
            return dt.strftime("%Y%m%dT0000")
        except ValueError:
            try:
                dt = datetime.strptime(date_input, "%Y-%m-%d %H:%M")
                return dt.strftime("%Y%m%dT%H%M")
            except ValueError:
                raise ValueError(f"Unsupported date format: {date_input}")
    elif isinstance(date_input, datetime):
        return date_input.strftime("%Y%m%dT%H%M")
    else:
        raise ValueError(f"Date must be string or datetime object, got {type(date_input)}")

class AlphaVantageRateLimitError(Exception):
    """Exception raised when Alpha Vantage API rate limit is exceeded."""
    pass

def _make_api_request(function_name: str, params: dict) -> dict | str:
    """Helper function to make API requests and handle responses.

    Includes a per-request timeout (default 60 s, override via DATA_API_TIMEOUT
    env var) and exponential-backoff retry on transient network/server errors
    (delays: 2 s → 4 s → 8 s).

    Raises:
        AlphaVantageRateLimitError: When API rate limit is exceeded
    """
    # Create a copy of params to avoid modifying the original
    api_params = params.copy()
    api_params.update({
        "function": function_name,
        "apikey": get_api_key(),
        "source": "trading_agents",
    })

    # Handle entitlement parameter if present in params or global variable
    current_entitlement = globals().get('_current_entitlement')
    entitlement = api_params.get("entitlement") or current_entitlement

    if entitlement:
        api_params["entitlement"] = entitlement
    elif "entitlement" in api_params:
        # Remove entitlement if it's None or empty
        api_params.pop("entitlement", None)

    # ── Proxy support (HTTP_PROXY / HTTPS_PROXY from env / .env) ─────────────
    proxies: dict | None = None
    http_proxy  = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    if http_proxy or https_proxy:
        proxies = {}
        if http_proxy:
            proxies["http"]  = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy

    debug = _debug_enabled()
    last_exc: Exception | None = None

    for attempt, delay in enumerate((*_DATA_RETRY_DELAYS, None), start=1):
        t0 = time.monotonic()
        try:
            if debug:
                logger.debug(
                    "[AlphaVantage] attempt=%d  function=%s  timeout=%ds",
                    attempt, function_name, _DATA_API_TIMEOUT,
                )
            response = requests.get(
                API_BASE_URL,
                params=api_params,
                timeout=_DATA_API_TIMEOUT,
                proxies=proxies,
            )
            elapsed = time.monotonic() - t0
            if debug:
                logger.debug(
                    "[AlphaVantage] OK  attempt=%d  status=%d  elapsed=%.2fs",
                    attempt, response.status_code, elapsed,
                )

            # Retry on transient 5xx server errors
            if response.status_code in _RETRYABLE_STATUS_CODES:
                raise requests.exceptions.HTTPError(
                    f"{response.status_code} Server Error", response=response
                )

            response.raise_for_status()

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as exc:
            elapsed = time.monotonic() - t0
            last_exc = exc

            # HTTPError from raise_for_status() for 4xx (e.g. 401, 404) is NOT
            # retryable — only 5xx errors are (handled above by the explicit
            # check).  Timeout and ConnectionError are always retryable.
            is_retryable = not isinstance(exc, requests.exceptions.HTTPError) or (
                getattr(getattr(exc, "response", None), "status_code", 0)
                in _RETRYABLE_STATUS_CODES
            )

            if debug:
                logger.debug(
                    "[AlphaVantage] error  attempt=%d  retryable=%s  elapsed=%.2fs  exc=%s",
                    attempt, is_retryable, elapsed, exc,
                )
            if not is_retryable or delay is None:
                raise
            logger.warning(
                "[AlphaVantage] Transient error – retrying in %ds (attempt %d/%d): %s",
                delay, attempt, len(_DATA_RETRY_DELAYS), exc,
            )
            time.sleep(delay)
            continue

        response_text = response.text

        # Check if response is JSON (error responses are typically JSON)
        try:
            response_json = json.loads(response_text)
            # Check for rate limit error
            if "Information" in response_json:
                info_message = response_json["Information"]
                if "rate limit" in info_message.lower() or "api key" in info_message.lower():
                    raise AlphaVantageRateLimitError(f"Alpha Vantage rate limit exceeded: {info_message}")
        except json.JSONDecodeError:
            # Response is not JSON (likely CSV data), which is normal
            pass

        return response_text

    raise last_exc  # type: ignore[misc]



def _filter_csv_by_date_range(csv_data: str, start_date: str, end_date: str) -> str:
    """
    Filter CSV data to include only rows within the specified date range.

    Args:
        csv_data: CSV string from Alpha Vantage API
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        Filtered CSV string
    """
    if not csv_data or csv_data.strip() == "":
        return csv_data

    try:
        # Parse CSV data
        df = pd.read_csv(StringIO(csv_data))

        # Assume the first column is the date column (timestamp)
        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col])

        # Filter by date range
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)

        filtered_df = df[(df[date_col] >= start_dt) & (df[date_col] <= end_dt)]

        # Convert back to CSV string
        return filtered_df.to_csv(index=False)

    except Exception as e:
        # If filtering fails, return original data with a warning
        print(f"Warning: Failed to filter CSV data by date range: {e}")
        return csv_data
