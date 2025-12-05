import matplotlib.pyplot as plt
import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime
import sys
from pathlib import Path

# Add your src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent / 'src'))

# Import your Black-Scholes pricing function
from models import black_scholes_price

def plot_option_model_errors(strikes, calc_prices, market_mids, expiry_label="", save_path=None):
    """Plot absolute and percentage model errors versus strike for a given expiry.
    
    Parameters:
    -----------
    strikes : list
        Strike prices
    calc_prices : list
        Calculated option prices from Black-Scholes
    market_mids : list
        Market mid-prices (bid+ask)/2
    expiry_label : str
        Expiration date label for title
    save_path : str, optional
        If provided, save plot to this path instead of showing. If None, display plot.
    """
    errors = [c - m for c, m in zip(calc_prices, market_mids)]
    pct_errors = [(e / m * 100) if m else 0 for e, m in zip(errors, market_mids)]

    plt.figure(figsize=(10, 6))
    plt.plot(strikes, errors, marker='o', label='Absolute Error ($)')
    plt.plot(strikes, pct_errors, marker='x', label='Percent Error (%)')
    plt.axhline(0, color='gray', linestyle='--', linewidth=1)
    plt.xlabel('Strike')
    plt.ylabel('Error')
    plt.title(f'Model vs Market Error - Expiry {expiry_label}')
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Plot saved to: {save_path}")
        plt.close()
    else:
        plt.show()

def real_world_test_historical_atm(ticker="AAPL", test_date="2025-10-15", max_options=10):
    """Test with ATM options (more liquid, better for validation)"""
    tk = yf.Ticker(ticker)
    hist = tk.history(start="2025-09-01", end=test_date)
    
    if len(hist) == 0:
        print(f"No historical data for {ticker}")
        return
    
    stock_price = hist['Close'].iloc[-1]
    
    returns = hist['Close'].pct_change().dropna()
    hist_vol = np.std(returns) * np.sqrt(252)
    
    test_datetime = datetime.strptime(test_date, "%Y-%m-%d")
    rf = 0.045
    
    expiry_dates = tk.options
    if not expiry_dates:
        print(f"No options for {ticker}")
        return
    
    print(f"\n{ticker} - Test Date: {test_date}")
    print(f"Stock Price: ${stock_price:.2f}")
    print(f"Historical Vol: {hist_vol:.2%}, Risk-Free: {rf:.2%}\n")
    
    for expiry_date in expiry_dates[:3]:  # Test first 3 expirations
        option_chain = tk.option_chain(expiry_date)
        calls = option_chain.calls
        
        atm_range = (stock_price * 0.95, stock_price * 1.05)
        atm_calls = calls[(calls['strike'] >= atm_range[0]) & (calls['strike'] <= atm_range[1])]
        
        if len(atm_calls) == 0:
            continue
        
        T = (datetime.strptime(expiry_date, "%Y-%m-%d") - test_datetime).days / 365
        
        if T <= 0:
            continue
        
        print(f"\nExpiry: {expiry_date} (T = {T:.4f} years = {T*365:.0f} days)")
        print(f"{'Strike':<8} {'Bid':<10} {'Ask':<10} {'Mid':<10} {'Calc':<10} {'Error':<10}")
        print("-" * 65)
        
        count = 0
        for idx, row in atm_calls.iterrows():
            K = row['strike']
            bid = row.get('bid', np.nan)
            ask = row.get('ask', np.nan)
            
            if not pd.isna(bid) and not pd.isna(ask) and bid > 0 and ask > 0:
                mid_price = (bid + ask) / 2
            else:
                mid_price = row.get('lastPrice', np.nan)
            
            if pd.isna(mid_price):
                continue
            
            market_iv = row.get('impliedVolatility', hist_vol)
            # DEBUG
            print(f"DEBUG: T={T:.6f}, Expiry={expiry_date}, TestDate={test_datetime}, S={stock_price}, K={K}, r={rf}, IV={market_iv:.6f}")
            print(f"DEBUG: Bid={bid}, Ask={ask}, Mid={mid_price}, IV Source={'market' if 'impliedVolatility' in row and not pd.isna(row['impliedVolatility']) else 'hist_vol'}")
            
            calc_price = black_scholes_price(stock_price, K, T, rf, market_iv, "call")
            print(f"DEBUG: BS Price Result = {calc_price}")
            error = calc_price - mid_price
            pct_error = (error / mid_price * 100) if mid_price > 0 else 0
            
            print(f"{K:<8.2f} ${bid:<9.2f} ${ask:<9.2f} ${mid_price:<9.2f} ${calc_price:<9.2f} ${error:<9.2f} {pct_error:<8.2f}%")
            count += 1
            if count >= max_options:
                break


def real_world_test_historical(ticker="AAPL", test_date="2025-10-15", max_options=10):
    """Test pricing using historical stock data but current option chain"""
    tk = yf.Ticker(ticker)
    hist = tk.history(start="2025-09-01", end=test_date)
    
    if len(hist) == 0:
        print(f"No historical data available for {ticker} on {test_date}")
        return
    
    if test_date not in hist.index.strftime('%Y-%m-%d'):
        # Use the closest date
        test_date = hist.index[-1].strftime('%Y-%m-%d')
        print(f"Requested date not available. Using closest: {test_date}")
    
    stock_price = hist.loc[hist.index.strftime('%Y-%m-%d') == test_date, 'Close'].values[0]
    returns = hist['Close'].pct_change().dropna()
    volatility = np.std(returns) * np.sqrt(252)
    rf = 0.045 # Or get latest 1m Treasury yield for realism
    
    expiry_dates = tk.options
    if not expiry_dates:
        print(f"No option chain found for {ticker}")
        return
    
    option_chain = tk.option_chain(expiry_dates[0]) # Use nearest upcoming expiry
    calls = option_chain.calls
    
    test_datetime = datetime.strptime(test_date, "%Y-%m-%d")
    
    print(f"\n{ticker} - Test Date: {test_date}")
    print(f"Stock Price: ${stock_price:.2f}, IV (1m hist): {volatility:.2%}, Risk-Free Rate: {rf:.2%}")
    print(f"{'Strike':<8} {'Market':<10} {'Calculated':<12} {'Difference':<12} {'% Error':<10}")
    print("-" * 60)
    
    count = 0
    for idx, row in calls.iterrows():
        K = row['strike']
        expiry = row['lastTradeDate']
        if not isinstance(expiry, str):
            expiry = expiry.strftime('%Y-%m-%d')
        T = (datetime.strptime(expiry, "%Y-%m-%d") - test_datetime).days / 365
        market_price = row.get('lastPrice', None)
        
        if T <= 0 or np.isnan(K) or pd.isna(market_price):
            continue
        
        calc_price = black_scholes_price(stock_price, K, T, rf, volatility, "call")
        diff = calc_price - market_price
        pct_error = (diff / market_price * 100) if market_price else 0
        
        print(f"{K:<8.2f} ${market_price:<9.2f} ${calc_price:<11.2f} ${diff:<11.2f} {pct_error:<9.1f}%")
        count += 1
        if count >= max_options:
            break
    if count == 0:
        print("No valid options to display.")

def test_atm_options_today(ticker="AAPL", min_days_to_expiry=30, max_options=10, plot_mode="show", plot_dir="./plots"):
    """Test ATM options from today's available expirations >= min_days_to_expiry from today."""
    """Analyze true ATM options (±2% from stock price), and always use market implied volatility for theoretical pricing.
    
    Parameters:
    -----------
    ticker : str
        Stock ticker symbol
    min_days_to_expiry : int
        Minimum days to expiration to include
    max_options : int
        Maximum options per expiry to analyze
    plot_mode : str
        "show" to display plots, "save" to save as files, "none" to skip plotting
    plot_dir : str
        Directory to save plots (used if plot_mode="save")
    """
    if plot_mode == "save":
        Path(plot_dir).mkdir(parents=True, exist_ok=True)
        print(f"Saving plots to: {plot_dir}")
    
    tk = yf.Ticker(ticker)

    # tk = yf.Ticker(ticker)
    
    # Get last available date's price (usually today)
    hist = tk.history(period="60d")
    stock_price = hist['Close'].iloc[-1]
    test_datetime = hist.index[-1]
    returns = hist['Close'].pct_change().dropna()
    hist_vol = np.std(returns) * np.sqrt(252)
    rf = 0.045
    
    expiry_dates = tk.options
    # Filter for expiries at least min_days_to_expiry out from now
    today = pd.Timestamp(datetime.now().date())
    valid_expiries = []
    for exp in expiry_dates:
        exp_dt = pd.Timestamp(exp)
        T_days = (exp_dt - today).days
        if T_days >= min_days_to_expiry:
            valid_expiries.append(exp)
    if not valid_expiries:
        print(f"No valid expiries at least {min_days_to_expiry} days out for {ticker}.")
        return
    
    print(f"\n{ticker} - Last Available Date: {test_datetime.strftime('%Y-%m-%d')}")
    print(f"Stock Price: ${stock_price:.2f}")
    print(f"Historical Vol: {hist_vol:.2%}, Risk-Free: {rf:.2%}\n")
    print(f"Using expiries at least {min_days_to_expiry} days out from today: {valid_expiries}")
    
    for expiry_date in valid_expiries[:3]:  # Limit to first 3 valid options
        option_chain = tk.option_chain(expiry_date)
        calls = option_chain.calls
        atm_range = (stock_price * 0.95, stock_price * 1.05)
        atm_calls = calls[(calls['strike'] >= atm_range[0]) & (calls['strike'] <= atm_range[1])]
        if len(atm_calls) == 0:
            continue

        # T = (pd.Timestamp(expiry_date) - pd.Timestamp(test_datetime)).days / 365
        T = (pd.Timestamp(expiry_date).tz_localize(None) - pd.Timestamp(test_datetime).tz_localize(None)).days / 365
        if T <= 0:
            continue
        print(f"\nExpiry: {expiry_date} (T = {T:.4f} years = {T*365:.0f} days)")
        print(f"{'Strike':<8} {'Bid':<10} {'Ask':<10} {'Mid':<10} {'Calc':<10} {'Error':<10} {'%Error':<10}")
        print("-" * 75)
        count = 0
        
        # Initialize containers for plotting
        strikes, calc_prices, market_mids = [], [], []
        for idx, row in atm_calls.iterrows():
            K = row['strike']
            bid = row.get('bid', np.nan)
            ask = row.get('ask', np.nan)
            
            if not pd.isna(bid) and not pd.isna(ask) and bid > 0 and ask > 0:
                mid_price = (bid + ask) / 2
            else:
                mid_price = row.get('lastPrice', np.nan)
            if pd.isna(mid_price):
                continue
            market_iv = row.get('impliedVolatility', hist_vol)
            print(f"DEBUG: T={T:.6f}, Expiry={expiry_date}, EvalDate={test_datetime}, S={stock_price}, K={K}, r={rf}, IV={market_iv:.6f}")
            print(f"DEBUG: Bid={bid}, Ask={ask}, Mid={mid_price}, IV Source={'market' if 'impliedVolatility' in row and not pd.isna(row['impliedVolatility']) else 'hist_vol'}")
            calc_price = black_scholes_price(stock_price, K, T, rf, market_iv, "call")
            print(f"DEBUG: BS Price Result = {calc_price}")
            error = calc_price - mid_price
            pct_error = (error / mid_price * 100) if mid_price > 0 else 0
            print(f"{K:<8.2f} ${bid:<9.2f} ${ask:<9.2f} ${mid_price:<9.2f} ${calc_price:<9.2f} ${error:<9.2f} {pct_error:<8.2f}%")
            
            # Collect data for plotting
            strikes.append(K)
            calc_prices.append(calc_price)
            market_mids.append(mid_price)

            count += 1
            if count >= max_options:
                break
                    
        # Plot errors for this expiry if data available and plot_mode is not "none"
        if strikes and plot_mode != "none":
            if plot_mode == "save":
                save_path = f"{plot_dir}/{ticker}_error_{expiry_date}.png"
                plot_option_model_errors(strikes, calc_prices, market_mids, expiry_label=expiry_date, save_path=save_path)
            else:  # show mode
                plot_option_model_errors(strikes, calc_prices, market_mids, expiry_label=expiry_date)

# test_atm_options_today("AAPL")

# Display plots (default)

# With function call - display plots
test_atm_options_today("AAPL", plot_mode="show")

# Save plots to directory
# test_atm_options_today("AAPL", plot_mode="save", plot_dir="./analysis_results")

# Skip plotting
test_atm_options_today("AAPL", plot_mode="none")

# real_world_test_historical_atm("AAPL", "2025-10-15")

# Example usage for several tickers and past dates
# real_world_test_historical("AAPL", "2025-10-15")
# real_world_test_historical("TSLA", "2025-10-20")
# real_world_test_historical("MSFT", "2025-10-10")
