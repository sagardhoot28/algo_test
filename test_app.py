"""Download historical equity data for symbols listed in a CSV file."""

from datetime import date, timedelta
import io
import re
import zipfile

import pandas as pd
import streamlit as st
import yfinance as yf


st.set_page_config(page_title="Equity Data Downloader", layout="wide")
st.title("Equity Data Downloader")
st.write(
    "Upload a CSV containing a **Symbol** column, choose a date range and interval, "
    "then download one CSV per symbol."
)

INTERVALS = {"Daily": "1d", "Weekly": "1wk", "Monthly": "1mo"}


def clean_symbol(value):
    """Use Yahoo Finance's NSE suffix for symbols without an exchange suffix."""
    if pd.isna(value):
        return ""
    symbol = str(value).strip().upper()
    if symbol and "." not in symbol:
        symbol += ".NS"
    return symbol


def safe_filename(symbol, interval_name, start, end):
    safe_symbol = re.sub(r"[^A-Z0-9._-]+", "_", symbol)
    return f"{safe_symbol}_{interval_name.lower()}_{start}_{end}.csv"


@st.cache_data(show_spinner=False)
def download_history(symbol, start, end_exclusive, interval):
    """Fetch one ticker. The end date is exclusive in yfinance."""
    try:
        frame = yf.download(
            tickers=symbol,
            start=start,
            end=end_exclusive,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
            multi_level_index=False,
        )
    except Exception as exc:
        return pd.DataFrame(), f"{symbol}: {exc}"

    if frame is None or frame.empty:
        return pd.DataFrame(), f"{symbol}: Yahoo Finance returned no data. Check the ticker and date range."

    # Handle yfinance versions that return a MultiIndex even for a single ticker.
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [column[0] for column in frame.columns]

    frame = frame.reset_index()
    if "Datetime" in frame.columns:
        frame = frame.rename(columns={"Datetime": "Date"})
    elif "index" in frame.columns:
        frame = frame.rename(columns={"index": "Date"})
    frame.insert(0, "Symbol", symbol)
    return frame, ""


def make_zip(csv_files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in csv_files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


uploaded = st.file_uploader("Upload symbols CSV", type="csv", help='The file must have a column named "Symbol".')
left, middle, right = st.columns(3)
with left:
    start_date = st.date_input("Start date", value=date.today() - timedelta(days=365))
with middle:
    end_date = st.date_input("End date", value=date.today())
with right:
    interval_name = st.selectbox("Time frame", list(INTERVALS))

if uploaded is None:
    st.info('Upload a CSV with a "Symbol" column to get started.')
    st.stop()

try:
    symbols_df = pd.read_csv(uploaded)
except Exception as exc:
    st.error(f"Could not read the uploaded CSV: {exc}")
    st.stop()

# Ignore accidental surrounding spaces in the CSV header.
symbols_df.columns = [str(column).strip() for column in symbols_df.columns]
symbol_column = next((column for column in symbols_df.columns if column.lower() == "symbol"), None)
if symbol_column is None:
    st.error('The uploaded CSV must contain a column named "Symbol".')
    st.stop()

symbols = list(dict.fromkeys(filter(None, symbols_df[symbol_column].map(clean_symbol))))
if not symbols:
    st.warning('No non-empty symbols were found in the "Symbol" column.')
    st.stop()

st.caption(f"Found {len(symbols)} unique symbol(s). Bare symbols use the NSE suffix (.NS).")
with st.expander("Symbols to download", expanded=False):
    st.dataframe(pd.DataFrame({"Symbol": symbols}), hide_index=True, width="stretch")

if start_date > end_date:
    st.error("Start date must be on or before the end date.")
    st.stop()

if "equity_csv_files" not in st.session_state:
    st.session_state.equity_csv_files = {}
    st.session_state.equity_errors = []
    st.session_state.equity_preview = pd.DataFrame()
    st.session_state.equity_zip_name = "equity_data.zip"

if st.button("Fetch data", type="primary", width="stretch"):
    files, errors, previews = {}, [], []
    progress = st.progress(0, text="Preparing downloads...")
    end_exclusive = end_date + timedelta(days=1)

    for index, symbol in enumerate(symbols, start=1):
        progress.progress((index - 1) / len(symbols), text=f"Fetching {symbol} ({index}/{len(symbols)})...")
        history, error = download_history(
            symbol, start_date.isoformat(), end_exclusive.isoformat(), INTERVALS[interval_name]
        )
        if error:
            errors.append(error)
        else:
            filename = safe_filename(symbol, interval_name, start_date.isoformat(), end_date.isoformat())
            files[filename] = history.to_csv(index=False).encode("utf-8-sig")
            previews.append(history.head(5))
        progress.progress(index / len(symbols), text=f"Processed {symbol} ({index}/{len(symbols)})")

    st.session_state.equity_csv_files = files
    st.session_state.equity_errors = errors
    st.session_state.equity_preview = pd.concat(previews, ignore_index=True) if previews else pd.DataFrame()
    st.session_state.equity_zip_name = (
        f"equity_data_{interval_name.lower()}_{start_date.isoformat()}_{end_date.isoformat()}.zip"
    )
    progress.empty()

files = st.session_state.equity_csv_files
if st.session_state.equity_errors:
    with st.expander(f"Symbols with issues ({len(st.session_state.equity_errors)})", expanded=True):
        for message in st.session_state.equity_errors:
            st.write(f"- {message}")

if files:
    st.success(f"Fetched data for {len(files)} of {len(symbols)} symbol(s).")
    if not st.session_state.equity_preview.empty:
        st.subheader("Data preview")
        st.dataframe(st.session_state.equity_preview, hide_index=True, width="stretch")

    st.download_button(
        "Download all symbol CSVs (ZIP)",
        data=make_zip(files),
        file_name=st.session_state.equity_zip_name,
        mime="application/zip",
        type="primary",
        width="stretch",
    )
    st.subheader("Download individual CSVs")
    for filename, content in files.items():
        st.download_button(
            f"Download {filename}",
            data=content,
            file_name=filename,
            mime="text/csv",
            key=f"download_{filename}",
        )
elif st.session_state.equity_errors:
    st.error("No symbol data was downloaded. Review the issues above and check the tickers or date range.")
