
# Create the complete, production-ready Python script file
script_content = '''"""
Options Pricing Pipeline
========================
A comprehensive tool for simulating option contract prices using the Black-Scholes model.

Author: Created for options pricing analysis
Date: October 2025
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
import json
from datetime import datetime, timedelta
from typing import Dict, List, Union


class OptionsPricingPipeline:
    """
    A comprehensive options pricing pipeline that simulates contract prices
    using the Black-Scholes model with configurable Greeks.
    
    Features:
    ---------
    - Black-Scholes pricing for European options
    - Complete Greeks calculations (Delta, Gamma, Theta, Vega, Rho)
    - Time-based price simulations
    - Price scenario analysis
    - JSON configuration support
    """
    
    def __init__(self, risk_free_rate: float = 0.05):
        """
        Initialize the options pricing pipeline.
        
        Parameters:
        -----------
        risk_free_rate : float
            Default annual risk-free interest rate (default: 0.05 or 5%)
        """
        self.risk_free_rate = risk_free_rate
        
    @staticmethod
    def _calculate_d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple:
        """
        Calculate d1 and d2 parameters for Black-Scholes formula.
        
        Parameters:
        -----------
        S : float - Current stock price
        K : float - Strike price
        T : float - Time to expiration (years)
        r : float - Risk-free rate
        sigma : float - Volatility
        
        Returns:
        --------
        tuple - (d1, d2)
        """
        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        return d1, d2
    
    def black_scholes_price(self, S: float, K: float, T: float, r: float, 
                           sigma: float, option_type: str = 'call') -> float:
        """
        Calculate Black-Scholes option price.
        
        Parameters:
        -----------
        S : float - Current stock price
        K : float - Strike price
        T : float - Time to expiration (in years)
        r : float - Risk-free interest rate (annual)
        sigma : float - Volatility (annual)
        option_type : str - 'call' or 'put'
        
        Returns:
        --------
        float - Option price
        """
        if T <= 0:
            # At expiration, return intrinsic value
            if option_type.lower() == 'call':
                return max(S - K, 0)
            else:
                return max(K - S, 0)
        
        d1, d2 = self._calculate_d1_d2(S, K, T, r, sigma)
        
        if option_type.lower() == 'call':
            price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:  # put
            price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        
        return price
    
    def calculate_greeks(self, S: float, K: float, T: float, r: float, 
                        sigma: float, option_type: str = 'call') -> Dict[str, float]:
        """
        Calculate all major Greeks for an option.
        
        Parameters:
        -----------
        S : float - Current stock price
        K : float - Strike price
        T : float - Time to expiration (years)
        r : float - Risk-free rate
        sigma : float - Volatility
        option_type : str - 'call' or 'put'
        
        Returns:
        --------
        dict - Dictionary containing Delta, Gamma, Theta, Vega, and Rho
        """
        if T <= 0:
            # At expiration, Greeks have specific values
            return {
                'Delta': 1.0 if (option_type == 'call' and S > K) else 0.0,
                'Gamma': 0.0,
                'Theta': 0.0,
                'Vega': 0.0,
                'Rho': 0.0
            }
        
        d1, d2 = self._calculate_d1_d2(S, K, T, r, sigma)
        
        # Common calculations
        pdf_d1 = norm.pdf(d1)
        sqrt_T = np.sqrt(T)
        
        # Delta
        if option_type.lower() == 'call':
            delta = norm.cdf(d1)
        else:
            delta = norm.cdf(d1) - 1
        
        # Gamma (same for calls and puts)
        gamma = pdf_d1 / (S * sigma * sqrt_T)
        
        # Vega (same for calls and puts) - per 1% change in volatility
        vega = S * pdf_d1 * sqrt_T / 100
        
        # Theta (per day)
        if option_type.lower() == 'call':
            theta = (-(S * pdf_d1 * sigma) / (2 * sqrt_T) - 
                    r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
        else:
            theta = (-(S * pdf_d1 * sigma) / (2 * sqrt_T) + 
                    r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365
        
        # Rho (per 1% change in interest rate)
        if option_type.lower() == 'call':
            rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100
        else:
            rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100
        
        return {
            'Delta': delta,
            'Gamma': gamma,
            'Theta': theta,
            'Vega': vega,
            'Rho': rho
        }
    
    def simulate_price_over_time(self, config: Dict, 
                                 time_points: Union[int, List[datetime]] = 20) -> pd.DataFrame:
        """
        Simulate option price at different time points.
        
        Parameters:
        -----------
        config : dict
            Configuration dictionary containing:
            - current_price: Current stock price
            - strike_price: Strike price
            - expiration_date: Expiration date (YYYY-MM-DD or datetime)
            - option_type: 'call' or 'put'
            - implied_volatility or volatility: Volatility value
            - risk_free_rate: Risk-free rate (optional)
        time_points : int or list
            Number of time points or list of specific dates
        
        Returns:
        --------
        pd.DataFrame - Simulation results with prices and Greeks over time
        """
        # Extract parameters from config
        S = config['current_price']
        K = config['strike_price']
        expiration = config['expiration_date']
        option_type = config.get('option_type', 'call')
        
        # Greeks can be used to set implied volatility or can be calculated
        if 'implied_volatility' in config:
            sigma = config['implied_volatility']
        elif 'volatility' in config:
            sigma = config['volatility']
        else:
            sigma = 0.25  # Default 25% volatility
        
        r = config.get('risk_free_rate', self.risk_free_rate)
        
        # Parse expiration date
        if isinstance(expiration, str):
            exp_date = datetime.strptime(expiration, '%Y-%m-%d')
        else:
            exp_date = expiration
        
        # Generate time points
        if isinstance(time_points, int):
            current_date = datetime.now()
            dates = pd.date_range(start=current_date, end=exp_date, periods=time_points)
        else:
            dates = time_points
        
        results = []
        
        for date in dates:
            # Calculate time to expiration in years
            if isinstance(date, pd.Timestamp):
                date = date.to_pydatetime()
            
            T = max((exp_date - date).days / 365.0, 0)
            
            # Calculate option price
            price = self.black_scholes_price(S, K, T, r, sigma, option_type)
            
            # Calculate Greeks
            greeks = self.calculate_greeks(S, K, T, r, sigma, option_type)
            
            # Calculate intrinsic and time value
            intrinsic = max(S - K, 0) if option_type == 'call' else max(K - S, 0)
            time_value = price - intrinsic
            
            # Store results
            result = {
                'Date': date,
                'Days_to_Expiration': (exp_date - date).days,
                'Time_to_Expiration_Years': T,
                'Option_Price': price,
                'Intrinsic_Value': intrinsic,
                'Time_Value': time_value,
                **greeks
            }
            results.append(result)
        
        return pd.DataFrame(results)
    
    def simulate_price_scenarios(self, config: Dict, 
                                price_range: tuple = None,
                                num_prices: int = 20) -> pd.DataFrame:
        """
        Simulate option prices across different underlying prices.
        
        Parameters:
        -----------
        config : dict - Configuration with all option parameters
        price_range : tuple - (min_price, max_price) or None for auto
        num_prices : int - Number of price points to simulate
        
        Returns:
        --------
        pd.DataFrame - Simulation results across price scenarios
        """
        S_current = config['current_price']
        K = config['strike_price']
        expiration = config['expiration_date']
        option_type = config.get('option_type', 'call')
        sigma = config.get('implied_volatility', config.get('volatility', 0.25))
        r = config.get('risk_free_rate', self.risk_free_rate)
        
        # Parse expiration date
        if isinstance(expiration, str):
            exp_date = datetime.strptime(expiration, '%Y-%m-%d')
        else:
            exp_date = expiration
        
        # Calculate time to expiration
        current_date = datetime.now()
        T = max((exp_date - current_date).days / 365.0, 0)
        
        # Generate price range
        if price_range is None:
            price_range = (S_current * 0.7, S_current * 1.3)
        
        prices = np.linspace(price_range[0], price_range[1], num_prices)
        
        results = []
        
        for S in prices:
            price = self.black_scholes_price(S, K, T, r, sigma, option_type)
            greeks = self.calculate_greeks(S, K, T, r, sigma, option_type)
            
            intrinsic = max(S - K, 0) if option_type == 'call' else max(K - S, 0)
            
            result = {
                'Underlying_Price': S,
                'Option_Price': price,
                'Moneyness': S / K,
                'Intrinsic_Value': intrinsic,
                **greeks
            }
            results.append(result)
        
        return pd.DataFrame(results)
    
    def load_config_from_json(self, json_string: str) -> Dict:
        """
        Load configuration from JSON string.
        
        Parameters:
        -----------
        json_string : str - JSON formatted configuration
        
        Returns:
        --------
        dict - Configuration dictionary
        """
        return json.loads(json_string)
    
    def load_config_from_file(self, filepath: str) -> Dict:
        """
        Load configuration from JSON file.
        
        Parameters:
        -----------
        filepath : str - Path to JSON configuration file
        
        Returns:
        --------
        dict - Configuration dictionary
        """
        with open(filepath, 'r') as f:
            return json.load(f)
    
    def save_results_to_csv(self, df: pd.DataFrame, filename: str):
        """
        Save simulation results to CSV file.
        
        Parameters:
        -----------
        df : pd.DataFrame - Results dataframe
        filename : str - Output filename
        """
        df.to_csv(filename, index=False)
        print(f"Results saved to {filename}")


# Example usage
if __name__ == "__main__":
    # Initialize pipeline
    pipeline = OptionsPricingPipeline()
    
    # Example configuration
    config = {
        "ticker": "AAPL",
        "current_price": 175.0,
        "strike_price": 180.0,
        "expiration_date": "2025-11-21",
        "option_type": "call",
        "implied_volatility": 0.30,
        "risk_free_rate": 0.045
    }
    
    # Calculate current price and Greeks
    exp_date = datetime.strptime(config['expiration_date'], '%Y-%m-%d')
    T = (exp_date - datetime.now()).days / 365.0
    
    price = pipeline.black_scholes_price(
        S=config['current_price'],
        K=config['strike_price'],
        T=T,
        r=config['risk_free_rate'],
        sigma=config['implied_volatility'],
        option_type=config['option_type']
    )
    
    greeks = pipeline.calculate_greeks(
        S=config['current_price'],
        K=config['strike_price'],
        T=T,
        r=config['risk_free_rate'],
        sigma=config['implied_volatility'],
        option_type=config['option_type']
    )
    
    print(f"Option Price: ${price:.2f}")
    print("\\nGreeks:")
    for greek, value in greeks.items():
        print(f"  {greek:8s}: {value:10.6f}")
    
    # Run time simulation
    time_sim = pipeline.simulate_price_over_time(config, time_points=10)
    print("\\nTime Simulation:")
    print(time_sim[['Days_to_Expiration', 'Option_Price', 'Delta', 'Theta']].head())
    
    # Run price scenarios
    price_sim = pipeline.simulate_price_scenarios(config, num_prices=10)
    print("\\nPrice Scenarios:")
    print(price_sim[['Underlying_Price', 'Option_Price', 'Delta']].head())
'''

# Save the complete script
with open('options_pricing_pipeline.py', 'w') as f:
    f.write(script_content)

print("✓ Complete Python script saved to 'options_pricing_pipeline.py'")
print("\nThe script includes:")
print("  • Full Black-Scholes implementation")
print("  • All Greeks calculations (Delta, Gamma, Theta, Vega, Rho)")
print("  • Time-based simulations")
print("  • Price scenario analysis")
print("  • JSON configuration support")
print("  • CSV export functionality")
print("  • Example usage in __main__ block")
