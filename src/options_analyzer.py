#!/usr/bin/env python3
"""
Options Analyzer - High-Level Interface
=======================================

Provides a convenient high-level interface for options analysis,
combining all modular components into an easy-to-use class.

Author: Restructured Options Pricing System
Date: October 2025
"""

import pandas as pd
from datetime import datetime
from typing import Dict, List, Union, Optional, Tuple
from pathlib import Path

from models import black_scholes_price, calculate_greeks, intrinsic_value
from analytics import (
    simulate_price_over_time, simulate_price_scenarios, 
    simulate_volatility_scenarios, compare_option_strategies
)
from analytics.visualization import (
    plot_price_evolution, plot_price_scenarios, 
    plot_volatility_surface, plot_strategy_comparison
)
from utils import (
    validate_option_config, export_summary_report, 
    create_export_directory, bulk_export
)


class OptionsAnalyzer:
    """
    High-level interface for options pricing and analysis.
    
    This class provides a convenient way to perform comprehensive options
    analysis including pricing, Greeks calculation, scenario analysis,
    and visualization.
    
    Example:
    --------
    >>> config = {
    ...     'ticker': 'AAPL',
    ...     'current_price': 175.0,
    ...     'strike_price': 180.0,
    ...     'expiration_date': '2025-11-21',
    ...     'option_type': 'call',
    ...     'implied_volatility': 0.30
    ... }
    >>> 
    >>> analyzer = OptionsAnalyzer(config)
    >>> price = analyzer.get_current_price()
    >>> greeks = analyzer.get_greeks()
    >>> analyzer.run_full_analysis(export_results=True)
    """
    
    def __init__(self, config: Dict, validate_config: bool = True):
        """
        Initialize the Options Analyzer.
        
        Parameters:
        -----------
        config : Dict
            Option configuration dictionary
        validate_config : bool
            Whether to validate the configuration (default: True)
        """
        self.config = config.copy()
        
        if validate_config:
            validate_option_config(self.config)
        
        # Set default risk-free rate if not provided
        if 'risk_free_rate' not in self.config:
            self.config['risk_free_rate'] = 0.045
        
        # Calculate current time to expiration
        self._update_time_to_expiration()
        
        # Storage for results
        self.results = {}
        self.figures = {}
    
    def _update_time_to_expiration(self):
        """Update time to expiration based on current date."""
        if isinstance(self.config['expiration_date'], str):
            exp_date = datetime.strptime(self.config['expiration_date'], '%Y-%m-%d')
        else:
            exp_date = self.config['expiration_date']
        
        current_date = datetime.now()
        self.time_to_expiry = max((exp_date - current_date).days / 365.0, 0)
        self.days_to_expiry = max((exp_date - current_date).days, 0)
    
    def get_current_price(self) -> float:
        """
        Get current option price using Black-Scholes.
        
        Returns:
        --------
        float
            Current option price
        """
        return black_scholes_price(
            S=self.config['current_price'],
            K=self.config['strike_price'],
            T=self.time_to_expiry,
            r=self.config['risk_free_rate'],
            sigma=self.config['implied_volatility'],
            option_type=self.config['option_type']
        )
    
    def get_greeks(self) -> Dict[str, float]:
        """
        Get all Greeks for the current option.
        
        Returns:
        --------
        Dict[str, float]
            Dictionary containing all Greeks
        """
        return calculate_greeks(
            S=self.config['current_price'],
            K=self.config['strike_price'],
            T=self.time_to_expiry,
            r=self.config['risk_free_rate'],
            sigma=self.config['implied_volatility'],
            option_type=self.config['option_type']
        )
    
    def get_intrinsic_value(self) -> float:
        """
        Get intrinsic value of the option.
        
        Returns:
        --------
        float
            Intrinsic value
        """
        return intrinsic_value(
            S=self.config['current_price'],
            K=self.config['strike_price'],
            option_type=self.config['option_type']
        )
    
    def get_time_value(self) -> float:
        """
        Get time value of the option.
        
        Returns:
        --------
        float
            Time value (option price - intrinsic value)
        """
        return self.get_current_price() - self.get_intrinsic_value()
    
    def analyze_time_decay(self, time_points: int = 20) -> pd.DataFrame:
        """
        Analyze option price evolution over time.
        
        Parameters:
        -----------
        time_points : int
            Number of time points to simulate
        
        Returns:
        --------
        pd.DataFrame
            Time decay analysis results
        """
        df = simulate_price_over_time(self.config, time_points)
        self.results['time_analysis'] = df
        return df
    
    def analyze_price_scenarios(self, price_range: Optional[Tuple[float, float]] = None,
                              num_prices: int = 25) -> pd.DataFrame:
        """
        Analyze option behavior across different underlying prices.
        
        Parameters:
        -----------
        price_range : Tuple[float, float], optional
            (min_price, max_price) range
        num_prices : int
            Number of price points to simulate
        
        Returns:
        --------
        pd.DataFrame
            Price scenario analysis results
        """
        df = simulate_price_scenarios(self.config, price_range, num_prices)
        self.results['price_scenarios'] = df
        return df
    
    def analyze_volatility_scenarios(self, vol_range: Tuple[float, float] = (0.1, 0.8),
                                   num_vols: int = 15) -> pd.DataFrame:
        """
        Analyze option sensitivity to volatility changes.
        
        Parameters:
        -----------
        vol_range : Tuple[float, float]
            (min_vol, max_vol) range
        num_vols : int
            Number of volatility points to simulate
        
        Returns:
        --------
        pd.DataFrame
            Volatility scenario analysis results
        """
        df = simulate_volatility_scenarios(self.config, vol_range, num_vols)
        self.results['volatility_scenarios'] = df
        return df
    
    def create_visualizations(self, save_dir: Optional[Union[str, Path]] = None) -> Dict[str, str]:
        """
        Create all standard visualizations.
        
        Parameters:
        -----------
        save_dir : Union[str, Path], optional
            Directory to save plots
        
        Returns:
        --------
        Dict[str, str]
            Dictionary mapping plot names to file paths
        """
        saved_plots = {}
        
        if 'time_analysis' in self.results:
            fig = plot_price_evolution(self.results['time_analysis'])
            self.figures['price_evolution'] = fig
            if save_dir:
                path = Path(save_dir) / 'price_evolution.png'
                fig.savefig(path, dpi=300, bbox_inches='tight')
                saved_plots['price_evolution'] = str(path)
        
        if 'price_scenarios' in self.results:
            fig = plot_price_scenarios(self.results['price_scenarios'])
            self.figures['price_scenarios'] = fig
            if save_dir:
                path = Path(save_dir) / 'price_scenarios.png'
                fig.savefig(path, dpi=300, bbox_inches='tight')
                saved_plots['price_scenarios'] = str(path)
        
        if 'volatility_scenarios' in self.results:
            fig = plot_volatility_surface(self.results['volatility_scenarios'])
            self.figures['volatility_surface'] = fig
            if save_dir:
                path = Path(save_dir) / 'volatility_surface.png'
                fig.savefig(path, dpi=300, bbox_inches='tight')
                saved_plots['volatility_surface'] = str(path)
        
        return saved_plots
    
    def run_full_analysis(self, export_results: bool = False, 
                         export_dir: Optional[Union[str, Path]] = None) -> Dict[str, pd.DataFrame]:
        """
        Run complete options analysis including all scenarios and visualizations.
        
        Parameters:
        -----------
        export_results : bool
            Whether to export results to files
        export_dir : Union[str, Path], optional
            Directory for exports (auto-generated if not provided)
        
        Returns:
        --------
        Dict[str, pd.DataFrame]
            Dictionary containing all analysis results
        """
        print(f"Running full analysis for {self.config.get('ticker', 'option')} {self.config['option_type']}...")
        
        # Run all analyses
        print("  ✓ Analyzing time decay...")
        self.analyze_time_decay()
        
        print("  ✓ Analyzing price scenarios...")
        self.analyze_price_scenarios()
        
        print("  ✓ Analyzing volatility scenarios...")
        self.analyze_volatility_scenarios()
        
        print("  ✓ Creating visualizations...")
        
        # Export if requested
        if export_results:
            if export_dir is None:
                export_dir = create_export_directory('./exports', self.config)
            else:
                export_dir = Path(export_dir)
                export_dir.mkdir(parents=True, exist_ok=True)
            
            print(f"  ✓ Exporting results to {export_dir}...")
            
            # Export data
            exported_files = bulk_export(self.results, self.config, export_dir)
            
            # Export summary report
            if 'time_analysis' in self.results and 'price_scenarios' in self.results:
                summary_path = export_summary_report(
                    self.config,
                    self.results['time_analysis'],
                    self.results['price_scenarios'],
                    export_dir / 'summary_report.xlsx'
                )
            
            # Create and save visualizations
            self.create_visualizations(export_dir)
            
            print(f"  ✓ Analysis complete. Results saved to: {export_dir}")
        
        return self.results
    
    def get_summary(self) -> Dict[str, Union[str, float]]:
        """
        Get a summary of the current option analysis.
        
        Returns:
        --------
        Dict[str, Union[str, float]]
            Summary statistics and information
        """
        current_price = self.get_current_price()
        greeks = self.get_greeks()
        intrinsic = self.get_intrinsic_value()
        time_value = self.get_time_value()
        
        moneyness = self.config['current_price'] / self.config['strike_price']
        
        if self.config['option_type'].lower() == 'call':
            status = 'ITM' if moneyness > 1 else ('ATM' if abs(moneyness - 1) < 0.02 else 'OTM')
        else:
            status = 'ITM' if moneyness < 1 else ('ATM' if abs(moneyness - 1) < 0.02 else 'OTM')
        
        return {
            'ticker': self.config.get('ticker', 'N/A'),
            'option_type': self.config['option_type'].title(),
            'strike_price': self.config['strike_price'],
            'current_stock_price': self.config['current_price'],
            'days_to_expiry': self.days_to_expiry,
            'moneyness_status': status,
            'moneyness_ratio': moneyness,
            'option_price': current_price,
            'intrinsic_value': intrinsic,
            'time_value': time_value,
            'delta': greeks['Delta'],
            'gamma': greeks['Gamma'],
            'theta': greeks['Theta'],
            'vega': greeks['Vega'],
            'rho': greeks['Rho'],
            'implied_volatility_pct': self.config['implied_volatility'] * 100
        }
    
    def print_summary(self):
        """Print a formatted summary of the option analysis."""
        summary = self.get_summary()
        
        print("\n" + "="*60)
        print(f"         OPTIONS ANALYSIS SUMMARY")
        print("="*60)
        print(f"Ticker:           {summary['ticker']}")
        print(f"Option Type:      {summary['option_type']}")
        print(f"Strike Price:     ${summary['strike_price']:.2f}")
        print(f"Current Price:    ${summary['current_stock_price']:.2f}")
        print(f"Days to Expiry:   {summary['days_to_expiry']}")
        print(f"Status:           {summary['moneyness_status']} (Moneyness: {summary['moneyness_ratio']:.3f})")
        print(f"Implied Vol:      {summary['implied_volatility_pct']:.1f}%")
        print("-"*60)
        print(f"Option Price:     ${summary['option_price']:.2f}")
        print(f"Intrinsic Value:  ${summary['intrinsic_value']:.2f}")
        print(f"Time Value:       ${summary['time_value']:.2f}")
        print("-"*60)
        print("GREEKS:")
        print(f"  Delta:          {summary['delta']:.4f}")
        print(f"  Gamma:          {summary['gamma']:.4f}")
        print(f"  Theta:          ${summary['theta']:.2f}/day")
        print(f"  Vega:           ${summary['vega']:.2f}/1% IV")
        print(f"  Rho:            ${summary['rho']:.2f}/1% rate")
        print("="*60)
