#!/usr/bin/env python3
"""
Basic Usage Examples
====================

Simple examples demonstrating how to use the modular options pricing system.

Author: Restructured Options Pricing System
Date: October 2025
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / 'src'))

from options_analyzer import OptionsAnalyzer
from utils.config import create_default_config, load_config_from_json


def example_1_basic_pricing():
    """Example 1: Basic option pricing and Greeks calculation."""
    print("\n" + "="*60)
    print("EXAMPLE 1: Basic Option Pricing")
    print("="*60)
    
    # Create a simple configuration
    config = {
        'ticker': 'AAPL',
        'current_price': 175.0,
        'strike_price': 180.0,
        'expiration_date': '2025-12-20',
        'option_type': 'call',
        'implied_volatility': 0.25,
        'risk_free_rate': 0.045
    }
    
    # Initialize analyzer
    analyzer = OptionsAnalyzer(config)
    
    # Get basic metrics
    current_price = analyzer.get_current_price()
    greeks = analyzer.get_greeks()
    intrinsic = analyzer.get_intrinsic_value()
    time_value = analyzer.get_time_value()
    
    print(f"Option Price: ${current_price:.2f}")
    print(f"Intrinsic Value: ${intrinsic:.2f}")
    print(f"Time Value: ${time_value:.2f}")
    print(f"\nGreeks:")
    for greek, value in greeks.items():
        print(f"  {greek}: {value:.4f}")


def example_2_time_analysis():
    """Example 2: Analyze time decay."""
    print("\n" + "="*60)
    print("EXAMPLE 2: Time Decay Analysis")
    print("="*60)
    
    config = create_default_config(
        ticker="TSLA",
        current_price=250.0,
        strike_price=260.0,
        days_to_expiry=45,
        option_type="call",
        implied_vol=0.40
    )
    
    analyzer = OptionsAnalyzer(config)
    
    # Analyze time decay
    time_df = analyzer.analyze_time_decay(time_points=10)
    
    print("Time Decay Analysis (first 5 rows):")
    print(time_df[['Days_to_Expiration', 'Option_Price', 'Time_Value', 'Theta']].head())
    
    # Show key insights
    initial_price = time_df.iloc[0]['Option_Price']
    final_intrinsic = time_df.iloc[-1]['Intrinsic_Value']
    max_time_value = time_df['Time_Value'].max()
    
    print(f"\nKey Insights:")
    print(f"  Current Option Price: ${initial_price:.2f}")
    print(f"  Expiry Intrinsic Value: ${final_intrinsic:.2f}")
    print(f"  Maximum Time Value: ${max_time_value:.2f}")


def example_3_price_scenarios():
    """Example 3: Price scenario analysis."""
    print("\n" + "="*60)
    print("EXAMPLE 3: Price Scenario Analysis")
    print("="*60)
    
    config = {
        'ticker': 'NVDA',
        'current_price': 500.0,
        'strike_price': 520.0,
        'expiration_date': '2025-11-15',
        'option_type': 'call',
        'implied_volatility': 0.35
    }
    
    analyzer = OptionsAnalyzer(config)
    
    # Analyze different underlying prices
    price_df = analyzer.analyze_price_scenarios(
        price_range=(450, 600),
        num_prices=10
    )
    
    print("Price Scenario Analysis:")
    print(price_df[['Underlying_Price', 'Option_Price', 'Delta', 'Gamma']].round(4))
    
    # Find break-even point (approximate)
    break_even_approx = config['strike_price'] + price_df.iloc[0]['Option_Price']
    print(f"\nApproximate Break-even Price: ${break_even_approx:.2f}")


def example_4_strategy_comparison():
    """Example 4: Compare different option strategies."""
    print("\n" + "="*60)
    print("EXAMPLE 4: Strategy Comparison")
    print("="*60)
    
    # Create configurations for a straddle strategy
    base_config = {
        'ticker': 'SPY',
        'current_price': 450.0,
        'strike_price': 450.0,
        'expiration_date': '2025-11-22',
        'implied_volatility': 0.20
    }
    
    # Call side of straddle
    call_config = base_config.copy()
    call_config.update({
        'name': 'Straddle Call',
        'option_type': 'call'
    })
    
    # Put side of straddle
    put_config = base_config.copy()
    put_config.update({
        'name': 'Straddle Put', 
        'option_type': 'put'
    })
    
    # Analyze both sides
    call_analyzer = OptionsAnalyzer(call_config)
    put_analyzer = OptionsAnalyzer(put_config)
    
    call_price = call_analyzer.get_current_price()
    put_price = put_analyzer.get_current_price()
    total_premium = call_price + put_price
    
    print(f"Long Straddle Analysis:")
    print(f"  Call Price: ${call_price:.2f}")
    print(f"  Put Price: ${put_price:.2f}")
    print(f"  Total Premium: ${total_premium:.2f}")
    print(f"  Break-even Points: ${450 - total_premium:.2f} and ${450 + total_premium:.2f}")


def example_5_full_analysis():
    """Example 5: Run complete analysis with exports."""
    print("\n" + "="*60)
    print("EXAMPLE 5: Complete Analysis")
    print("="*60)
    
    # Load configuration from file
    try:
        config_data = load_config_from_json('../config/option_configs.json')
        config = config_data['configurations'][0]  # Use first configuration
    except:
        # Fallback to manual config if file not found
        config = create_default_config(
            ticker="AAPL",
            current_price=175.0,
            strike_price=180.0,
            days_to_expiry=30
        )
    
    analyzer = OptionsAnalyzer(config)
    
    # Print summary first
    analyzer.print_summary()
    
    # Run full analysis (without export for example)
    results = analyzer.run_full_analysis(export_results=True)
    
    print(f"\nAnalysis complete! Generated {len(results)} result sets.")
    print(f"Available results: {list(results.keys())}")


if __name__ == "__main__":
    print("Options Pricing System - Usage Examples")
    
    # Run all examples
    example_1_basic_pricing()
    example_2_time_analysis()
    example_3_price_scenarios() 
    example_4_strategy_comparison()
    example_5_full_analysis()
    
    print("\n" + "="*60)
    print("All examples completed successfully!")
    print("="*60)
