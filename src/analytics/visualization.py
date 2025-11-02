from models.black_scholes import black_scholes_price, calculate_greeks, intrinsic_value
from models.black_scholes import black_scholes_price, calculate_greeks, intrinsic_value
#!/usr/bin/env python3
"""
Option Analytics Visualization
==============================

Provides plotting functions for visualizing option pricing behavior,
Greeks evolution, and scenario analysis.

Author: Restructured Options Pricing System
Date: October 2025
"""

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import seaborn as sns

# Set up plotting style
plt.style.use('default')
sns.set_palette("husl")


def plot_price_evolution(df: pd.DataFrame, save_path: Optional[str] = None) -> plt.Figure:
    """
    Plot option price evolution over time.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Time simulation results from simulate_price_over_time
    save_path : str, optional
        Path to save the plot
    
    Returns:
    --------
    plt.Figure
        The matplotlib figure object
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
    
    # Plot 1: Price components
    ax1.plot(df['Days_to_Expiration'], df['Option_Price'], 'b-', linewidth=2, label='Total Price')
    ax1.plot(df['Days_to_Expiration'], df['Intrinsic_Value'], 'g--', linewidth=2, label='Intrinsic Value')
    ax1.plot(df['Days_to_Expiration'], df['Time_Value'], 'r:', linewidth=2, label='Time Value')
    
    ax1.set_xlabel('Days to Expiration')
    ax1.set_ylabel('Option Price ($)')
    ax1.set_title('Option Price Evolution Over Time')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.invert_xaxis()  # Show time moving forward (decreasing days)
    
    # Plot 2: Key Greeks
    ax2_twin = ax2.twinx()
    
    # Delta and Gamma on left axis
    line1 = ax2.plot(df['Days_to_Expiration'], df['Delta'], 'purple', linewidth=2, label='Delta')
    line2 = ax2.plot(df['Days_to_Expiration'], df['Gamma'], 'orange', linewidth=2, label='Gamma')
    
    # Theta on right axis
    line3 = ax2_twin.plot(df['Days_to_Expiration'], df['Theta'], 'red', linewidth=2, label='Theta')
    
    ax2.set_xlabel('Days to Expiration')
    ax2.set_ylabel('Delta / Gamma', color='purple')
    ax2_twin.set_ylabel('Theta ($/day)', color='red')
    ax2.set_title('Greeks Evolution Over Time')
    ax2.grid(True, alpha=0.3)
    ax2.invert_xaxis()
    
    # Combine legends
    lines = line1 + line2 + line3
    labels = [l.get_label() for l in lines]
    ax2.legend(lines, labels, loc='upper right')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
    
    return fig


def plot_price_scenarios(df: pd.DataFrame, save_path: Optional[str] = None) -> plt.Figure:
    """
    Plot option price across different underlying prices.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Price scenario results from simulate_price_scenarios
    save_path : str, optional
        Path to save the plot
    
    Returns:
    --------
    plt.Figure
        The matplotlib figure object
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # Plot 1: Price components vs underlying price
    ax1.plot(df['Underlying_Price'], df['Option_Price'], 'b-', linewidth=2, label='Total Price')
    ax1.plot(df['Underlying_Price'], df['Intrinsic_Value'], 'g--', linewidth=2, label='Intrinsic Value')
    ax1.plot(df['Underlying_Price'], df['Time_Value'], 'r:', linewidth=2, label='Time Value')
    
    ax1.set_xlabel('Underlying Stock Price ($)')
    ax1.set_ylabel('Option Price ($)')
    ax1.set_title('Option Price vs Underlying Price')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Delta and Gamma
    ax2_twin = ax2.twinx()
    
    line1 = ax2.plot(df['Underlying_Price'], df['Delta'], 'purple', linewidth=2, label='Delta')
    line2 = ax2_twin.plot(df['Underlying_Price'], df['Gamma'], 'orange', linewidth=2, label='Gamma')
    
    ax2.set_xlabel('Underlying Stock Price ($)')
    ax2.set_ylabel('Delta', color='purple')
    ax2_twin.set_ylabel('Gamma', color='orange')
    ax2.set_title('Delta and Gamma vs Underlying Price')
    ax2.grid(True, alpha=0.3)
    
    # Combine legends
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax2.legend(lines, labels, loc='upper right')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
    
    return fig


def plot_volatility_surface(df: pd.DataFrame, save_path: Optional[str] = None) -> plt.Figure:
    """
    Plot option price sensitivity to implied volatility.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Volatility scenario results from simulate_volatility_scenarios
    save_path : str, optional
        Path to save the plot
    
    Returns:
    --------
    plt.Figure
        The matplotlib figure object
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # Plot 1: Price vs volatility
    ax1.plot(df['IV_Percentage'], df['Option_Price'], 'b-', linewidth=2, label='Option Price')
    ax1.plot(df['IV_Percentage'], df['Time_Value'], 'r:', linewidth=2, label='Time Value')
    
    ax1.set_xlabel('Implied Volatility (%)')
    ax1.set_ylabel('Price ($)')
    ax1.set_title('Option Price vs Implied Volatility')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Vega
    ax2.plot(df['IV_Percentage'], df['Vega'], 'green', linewidth=2, label='Vega')
    
    ax2.set_xlabel('Implied Volatility (%)')
    ax2.set_ylabel('Vega ($/1% IV change)')
    ax2.set_title('Vega vs Implied Volatility')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
    
    return fig


def plot_strategy_comparison(df: pd.DataFrame, x_col: str, y_col: str = 'Option_Price',
                           strategy_col: str = 'Strategy', save_path: Optional[str] = None) -> plt.Figure:
    """
    Plot comparison of multiple option strategies.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Comparison results from compare_option_strategies
    x_col : str
        Column name for x-axis
    y_col : str
        Column name for y-axis (default: 'Option_Price')
    strategy_col : str
        Column name that identifies different strategies
    save_path : str, optional
        Path to save the plot
    
    Returns:
    --------
    plt.Figure
        The matplotlib figure object
    """
    fig, ax = plt.subplots(figsize=(12, 8))
    
    strategies = df[strategy_col].unique()
    colors = plt.cm.Set1(np.linspace(0, 1, len(strategies)))
    
    for i, strategy in enumerate(strategies):
        strategy_data = df[df[strategy_col] == strategy]
        ax.plot(strategy_data[x_col], strategy_data[y_col], 
               linewidth=2, label=strategy, color=colors[i])
    
    ax.set_xlabel(x_col.replace('_', ' ').title())
    ax.set_ylabel(y_col.replace('_', ' ').title())
    ax.set_title(f'{y_col.replace("_", " ").title()} Comparison Across Strategies')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
    
    return fig


def plot_greeks_heatmap(df: pd.DataFrame, save_path: Optional[str] = None) -> plt.Figure:
    """
    Create a heatmap of Greeks values across different scenarios.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Simulation results containing Greeks
    save_path : str, optional
        Path to save the plot
    
    Returns:
    --------
    plt.Figure
        The matplotlib figure object
    """
    greeks_cols = ['Delta', 'Gamma', 'Theta', 'Vega', 'Rho']
    greeks_data = df[greeks_cols]
    
    fig, ax = plt.subplots(figsize=(10, 8))
    
    im = ax.imshow(greeks_data.T, cmap='RdYlBu', aspect='auto')
    
    # Set ticks and labels
    ax.set_yticks(range(len(greeks_cols)))
    ax.set_yticklabels(greeks_cols)
    ax.set_xlabel('Scenario Index')
    ax.set_title('Greeks Heatmap Across Scenarios')
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Greek Value')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
    
    return fig
