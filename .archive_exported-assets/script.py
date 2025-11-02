
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
    """
    
    def __init__(self):
        self.risk_free_rate = 0.05  # Default 5% annual risk-free rate
        
    @staticmethod
    def _calculate_d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple:
        """Calculate d1 and d2 for Black-Scholes formula"""
        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        return d1, d2
    
    def black_scholes_price(self, S: float, K: float, T: float, r: float, 
                           sigma: float, option_type: str = 'call') -> float:
        """
        Calculate Black-Scholes option price
        
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
        Calculate all major Greeks for an option
        
        Returns:
        --------
        dict - Contains Delta, Gamma, Theta, Vega, and Rho
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
        Simulate option price at different time points
        
        Parameters:
        -----------
        config : dict - Configuration with all option parameters
        time_points : int or list - Number of time points or specific dates
        
        Returns:
        --------
        pd.DataFrame - Simulation results
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
            
            # Store results
            result = {
                'Date': date,
                'Days_to_Expiration': (exp_date - date).days,
                'Time_to_Expiration_Years': T,
                'Option_Price': price,
                'Intrinsic_Value': max(S - K, 0) if option_type == 'call' else max(K - S, 0),
                'Time_Value': price - (max(S - K, 0) if option_type == 'call' else max(K - S, 0)),
                **greeks
            }
            results.append(result)
        
        return pd.DataFrame(results)
    
    def simulate_price_scenarios(self, config: Dict, 
                                price_range: tuple = None,
                                num_prices: int = 20) -> pd.DataFrame:
        """
        Simulate option prices across different underlying prices
        
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
            
            result = {
                'Underlying_Price': S,
                'Option_Price': price,
                'Moneyness': S / K,
                'Intrinsic_Value': max(S - K, 0) if option_type == 'call' else max(K - S, 0),
                **greeks
            }
            results.append(result)
        
        return pd.DataFrame(results)
    
    def load_config_from_json(self, json_string: str) -> Dict:
        """Load configuration from JSON string"""
        return json.loads(json_string)
    
    def save_results_to_csv(self, df: pd.DataFrame, filename: str):
        """Save simulation results to CSV"""
        df.to_csv(filename, index=False)
        print(f"Results saved to {filename}")


# Create instance
pipeline = OptionsPricingPipeline()

print("✓ Options Pricing Pipeline initialized successfully!")
print("\nAvailable methods:")
print("  - black_scholes_price(): Calculate option price")
print("  - calculate_greeks(): Calculate all Greeks")
print("  - simulate_price_over_time(): Simulate price evolution")
print("  - simulate_price_scenarios(): Simulate across price ranges")
