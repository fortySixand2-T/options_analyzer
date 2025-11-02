#!/usr/bin/env python3
"""
Advanced Trading Strategies Examples
====================================

Examples of complex options strategies and analysis techniques.

Author: Restructured Options Pricing System
Date: October 2025
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

# Add the src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent / 'src'))

from options_analyzer import OptionsAnalyzer
from utils.config import create_strategy_configs, create_default_config
from analytics.simulations import compare_option_strategies

def iron_condor_analysis():
    """Analyze an Iron Condor strategy."""
    print("\n" + "="*60)
    print("IRON CONDOR STRATEGY ANALYSIS")
    print("="*60)
    
    base_price = 100.0
    
    # Iron Condor: Sell OTM put and call, buy further OTM put and call
    configs = [
        {
            'name': 'Long Put (Wing)',
            'ticker': 'XYZ',
            'current_price': base_price,
            'strike_price': 90.0,  # Buy put
            'expiration_date': '2025-12-20',
            'option_type': 'put',
            'implied_volatility': 0.25,
            'position': -1  # Long position
        },
        {
            'name': 'Short Put (Body)',
            'ticker': 'XYZ', 
            'current_price': base_price,
            'strike_price': 95.0,  # Sell put
            'expiration_date': '2025-12-20',
            'option_type': 'put',
            'implied_volatility': 0.25,
            'position': 1   # Short position
        },
        {
            'name': 'Short Call (Body)',
            'ticker': 'XYZ',
            'current_price': base_price,
            'strike_price': 105.0,  # Sell call
            'expiration_date': '2025-12-20',
            'option_type': 'call',
            'implied_volatility': 0.25,
            'position': 1   # Short position
        },
        {
            'name': 'Long Call (Wing)',
            'ticker': 'XYZ',
            'current_price': base_price,
            'strike_price': 110.0,  # Buy call
            'expiration_date': '2025-12-20',
            'option_type': 'call',
            'implied_volatility': 0.25,
            'position': -1  # Long position
        }
    ]
    
    print("Iron Condor Components:")
    total_premium = 0
    
    for config in configs:
        analyzer = OptionsAnalyzer(config, validate_config=False)
        price = analyzer.get_current_price()
        position_value = price * config['position']
        total_premium += position_value
        
        position_type = "SELL" if config['position'] > 0 else "BUY"
        print(f"  {position_type} {config['name']}: ${price:.2f}")
    
    print(f"\nNet Premium Collected: ${total_premium:.2f}")
    print(f"Maximum Profit: ${total_premium:.2f}")
    print(f"Maximum Loss: ${5.0 - total_premium:.2f}")
    print(f"Profit Zone: $95 to $105 (between short strikes)")


def volatility_skew_analysis():
    """Analyze the same option with different volatility assumptions."""
    print("\n" + "="*60)
    print("VOLATILITY SKEW ANALYSIS")
    print("="*60)
    
    base_config = {
        'ticker': 'SKEW',
        'current_price': 200.0,
        'strike_price': 200.0,
        'expiration_date': '2025-12-15',
        'option_type': 'call'
    }
    
    # Different volatility scenarios
    vol_scenarios = {
        'Low Vol (Earnings Crush)': 0.15,
        'Normal Vol': 0.25,
        'High Vol (Event Risk)': 0.45,
        'Extreme Vol (Crisis)': 0.80
    }
    
    print("ATM Call Option Prices under Different Volatility Scenarios:")
    print("-" * 65)
    
    results = []
    for scenario_name, vol in vol_scenarios.items():
        config = base_config.copy()
        config['implied_volatility'] = vol
        
        analyzer = OptionsAnalyzer(config, validate_config=False)
        price = analyzer.get_current_price()
        greeks = analyzer.get_greeks()
        
        results.append({
            'Scenario': scenario_name,
            'IV': f"{vol*100:.0f}%",
            'Price': f"${price:.2f}",
            'Delta': f"{greeks['Delta']:.3f}",
            'Vega': f"${greeks['Vega']:.2f}"
        })
        
        print(f"{scenario_name:20s} | IV: {vol*100:3.0f}% | Price: ${price:6.2f} | Vega: ${greeks['Vega']:5.2f}")
    
    print("-" * 65)
    print("Note: Vega shows sensitivity to 1% IV change")


def earnings_play_analysis():
    """Analyze an earnings strangle strategy."""
    print("\n" + "="*60)
    print("EARNINGS PLAY: LONG STRANGLE ANALYSIS")
    print("="*60)
    
    # Pre-earnings setup
    current_price = 150.0
    
    configs = [
        {
            'name': 'OTM Put',
            'ticker': 'EARN',
            'current_price': current_price,
            'strike_price': 140.0,  # 7% OTM put
            'expiration_date': '2025-11-15',  # Week after earnings
            'option_type': 'put',
            'implied_volatility': 0.60  # High pre-earnings IV
        },
        {
            'name': 'OTM Call',
            'ticker': 'EARN',
            'current_price': current_price, 
            'strike_price': 160.0,  # 7% OTM call
            'expiration_date': '2025-11-15',
            'option_type': 'call',
            'implied_volatility': 0.60  # High pre-earnings IV
        }
    ]
    
    # Analyze current premiums
    total_cost = 0
    print("Pre-Earnings Strangle Setup:")
    
    for config in configs:
        analyzer = OptionsAnalyzer(config, validate_config=False)
        price = analyzer.get_current_price()
        greeks = analyzer.get_greeks()
        total_cost += price
        
        print(f"  {config['name']}: ${price:.2f} (Delta: {greeks['Delta']:.3f}, Vega: {greeks['Vega']:.2f})")
    
    print(f"\nTotal Premium Paid: ${total_cost:.2f}")
    
    # Calculate break-even points
    put_breakeven = 140.0 - total_cost
    call_breakeven = 160.0 + total_cost
    
    print(f"Break-even Points: ${put_breakeven:.2f} and ${call_breakeven:.2f}")
    print(f"Required Move: {abs(put_breakeven - current_price)/current_price*100:.1f}% down or {abs(call_breakeven - current_price)/current_price*100:.1f}% up")
    
    # Post-earnings IV crush simulation
    print("\nPost-Earnings IV Crush Scenario (IV drops to 25%):")
    
    # Simulate different stock price outcomes
    outcomes = [130, 140, 150, 160, 170]  # Different post-earnings prices
    
    for outcome_price in outcomes:
        scenario_pnl = 0
        
        for config in configs:
            # Update config for post-earnings scenario
            post_config = config.copy()
            post_config['current_price'] = outcome_price
            post_config['implied_volatility'] = 0.25  # IV crush
            
            analyzer = OptionsAnalyzer(post_config, validate_config=False)
            post_price = analyzer.get_current_price()
            
            # P&L calculation (we bought these options)
            original_price = OptionsAnalyzer(config, validate_config=False).get_current_price()
            pnl = post_price - original_price
            scenario_pnl += pnl
        
        print(f"  Stock @ ${outcome_price}: Total P&L = ${scenario_pnl:.2f}")


def risk_management_analysis():
    """Demonstrate risk management using Greeks."""
    print("\n" + "="*60)
    print("RISK MANAGEMENT WITH GREEKS")
    print("="*60)
    
    # Portfolio of different options
    portfolio = [
        {
            'name': 'Long Call 1',
            'ticker': 'RISK',
            'current_price': 100.0,
            'strike_price': 95.0,
            'expiration_date': '2025-12-20',
            'option_type': 'call',
            'implied_volatility': 0.30,
            'quantity': 10  # 10 contracts
        },
        {
            'name': 'Short Call 2',
            'ticker': 'RISK',
            'current_price': 100.0,
            'strike_price': 105.0, 
            'expiration_date': '2025-12-20',
            'option_type': 'call',
            'implied_volatility': 0.28,
            'quantity': -5  # Short 5 contracts
        },
        {
            'name': 'Long Put',
            'ticker': 'RISK',
            'current_price': 100.0,
            'strike_price': 95.0,
            'expiration_date': '2025-12-20', 
            'option_type': 'put',
            'implied_volatility': 0.32,
            'quantity': 3   # 3 contracts
        }
    ]
    
    print("Portfolio Risk Analysis:")
    print("-" * 80)
    
    total_delta = 0
    total_gamma = 0
    total_theta = 0
    total_vega = 0
    total_value = 0
    
    for position in portfolio:
        analyzer = OptionsAnalyzer(position, validate_config=False)
        price = analyzer.get_current_price()
        greeks = analyzer.get_greeks()
        
        # Scale by quantity (each contract is typically 100 shares)
        qty = position['quantity']
        position_value = price * qty * 100
        position_delta = greeks['Delta'] * qty * 100
        position_gamma = greeks['Gamma'] * qty * 100
        position_theta = greeks['Theta'] * qty * 100
        position_vega = greeks['Vega'] * qty * 100
        
        total_value += position_value
        total_delta += position_delta
        total_gamma += position_gamma
        total_theta += position_theta
        total_vega += position_vega
        
        print(f"{position['name']:12s} | Qty: {qty:3d} | Value: ${position_value:8.0f} | Delta: {position_delta:6.0f}")
    
    print("-" * 80)
    print(f"{'PORTFOLIO TOTALS':12s} | Value: ${total_value:8.0f} | Delta: {total_delta:6.0f}")
    print(f"")
    print(f"Risk Metrics:")
    print(f"  Total Delta: {total_delta:.0f} (equivalent to {total_delta:.0f} shares)")
    print(f"  Total Gamma: {total_gamma:.0f} (delta change per $1 stock move)")
    print(f"  Total Theta: ${total_theta:.0f}/day (daily time decay)")
    print(f"  Total Vega:  ${total_vega:.0f}/1% IV change")
    
    # Risk scenarios
    print(f"\nRisk Scenarios:")
    print(f"  $1 stock move up: ~${total_delta:.0f} P&L")
    print(f"  1% IV increase: ~${total_vega:.0f} P&L")
    print(f"  One day passing: ~${total_theta:.0f} P&L")


if __name__ == "__main__":
    print("Advanced Options Strategies - Examples")
    
    iron_condor_analysis()
    volatility_skew_analysis()
    earnings_play_analysis()
    risk_management_analysis()
    
    print("\n" + "="*60)
    print("All advanced examples completed!")
    print("="*60)
