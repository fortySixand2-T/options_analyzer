#!/usr/bin/env python3
"""
Configuration Management Utilities
==================================

Provides functions for loading, validating, and managing option configurations.

Author: Restructured Options Pricing System
Date: October 2025
"""

import json
import yaml
from datetime import datetime, timedelta
from typing import Dict, List, Union, Any
from pathlib import Path


def load_config_from_json(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Load configuration from JSON file.
    
    Parameters:
    -----------
    file_path : Union[str, Path]
        Path to JSON configuration file
    
    Returns:
    --------
    Dict[str, Any]
        Loaded configuration dictionary
    """
    with open(file_path, 'r') as f:
        return json.load(f)


def load_config_from_yaml(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Load configuration from YAML file.
    
    Parameters:
    -----------
    file_path : Union[str, Path]
        Path to YAML configuration file
    
    Returns:
    --------
    Dict[str, Any]
        Loaded configuration dictionary
    """
    with open(file_path, 'r') as f:
        return yaml.safe_load(f)


def save_config_to_json(config: Dict[str, Any], file_path: Union[str, Path], indent: int = 2):
    """
    Save configuration to JSON file.
    
    Parameters:
    -----------
    config : Dict[str, Any]
        Configuration dictionary to save
    file_path : Union[str, Path]
        Path where to save the JSON file
    indent : int
        JSON indentation (default: 2)
    """
    with open(file_path, 'w') as f:
        json.dump(config, f, indent=indent, default=str)


def save_config_to_yaml(config: Dict[str, Any], file_path: Union[str, Path]):
    """
    Save configuration to YAML file.
    
    Parameters:
    -----------
    config : Dict[str, Any]
        Configuration dictionary to save
    file_path : Union[str, Path]
        Path where to save the YAML file
    """
    with open(file_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def validate_option_config(config: Dict[str, Any]) -> bool:
    """
    Validate option configuration parameters.
    
    Parameters:
    -----------
    config : Dict[str, Any]
        Option configuration to validate
    
    Returns:
    --------
    bool
        True if valid, raises ValueError if invalid
    
    Raises:
    -------
    ValueError
        If configuration is invalid
    """
    required_fields = [
        'current_price', 'strike_price', 'expiration_date',
        'option_type', 'implied_volatility'
    ]
    
    # Check required fields
    for field in required_fields:
        if field not in config:
            raise ValueError(f"Missing required field: {field}")
    
    # Validate numeric fields
    numeric_fields = ['current_price', 'strike_price', 'implied_volatility']
    for field in numeric_fields:
        if not isinstance(config[field], (int, float)) or config[field] <= 0:
            raise ValueError(f"{field} must be a positive number")
    
    # Validate option type
    if config['option_type'].lower() not in ['call', 'put']:
        raise ValueError("option_type must be 'call' or 'put'")
    
    # Validate expiration date
    if isinstance(config['expiration_date'], str):
        try:
            exp_date = datetime.strptime(config['expiration_date'], '%Y-%m-%d')
            if exp_date <= datetime.now():
                raise ValueError("expiration_date must be in the future")
        except ValueError as e:
            if "does not match format" in str(e):
                raise ValueError("expiration_date must be in YYYY-MM-DD format")
            raise
    
    # Validate optional fields
    if 'risk_free_rate' in config:
        if not isinstance(config['risk_free_rate'], (int, float)):
            raise ValueError("risk_free_rate must be a number")
    
    return True


def create_default_config(ticker: str = "AAPL", 
                         current_price: float = 175.0,
                         strike_price: float = 180.0,
                         days_to_expiry: int = 30,
                         option_type: str = "call",
                         implied_vol: float = 0.25) -> Dict[str, Any]:
    """
    Create a default option configuration.
    
    Parameters:
    -----------
    ticker : str
        Stock ticker symbol
    current_price : float
        Current stock price
    strike_price : float
        Option strike price
    days_to_expiry : int
        Days until expiration
    option_type : str
        'call' or 'put'
    implied_vol : float
        Implied volatility (as decimal, e.g., 0.25 for 25%)
    
    Returns:
    --------
    Dict[str, Any]
        Default configuration dictionary
    """
    exp_date = datetime.now() + timedelta(days=days_to_expiry)
    
    return {
        'name': f'{ticker} {option_type.title()} ${strike_price}',
        'ticker': ticker,
        'current_price': current_price,
        'strike_price': strike_price,
        'expiration_date': exp_date.strftime('%Y-%m-%d'),
        'option_type': option_type.lower(),
        'implied_volatility': implied_vol,
        'risk_free_rate': 0.045,
        'notes': f'Default {option_type} option configuration'
    }


def create_strategy_configs(base_config: Dict[str, Any], strategy_type: str) -> List[Dict[str, Any]]:
    """
    Create multiple configurations for common option strategies.
    
    Parameters:
    -----------
    base_config : Dict[str, Any]
        Base option configuration
    strategy_type : str
        Strategy type: 'straddle', 'strangle', 'spread', 'collar'
    
    Returns:
    --------
    List[Dict[str, Any]]
        List of configurations for the strategy
    """
    configs = []
    S = base_config['current_price']
    
    if strategy_type.lower() == 'straddle':
        # Long straddle: buy call and put at same strike
        call_config = base_config.copy()
        call_config['option_type'] = 'call'
        call_config['name'] = f"Straddle Call - {base_config.get('ticker', 'Stock')}"
        
        put_config = base_config.copy()
        put_config['option_type'] = 'put'
        put_config['name'] = f"Straddle Put - {base_config.get('ticker', 'Stock')}"
        
        configs = [call_config, put_config]
    
    elif strategy_type.lower() == 'strangle':
        # Long strangle: buy OTM call and put
        call_config = base_config.copy()
        call_config['option_type'] = 'call'
        call_config['strike_price'] = S * 1.05  # 5% OTM call
        call_config['name'] = f"Strangle Call - {base_config.get('ticker', 'Stock')}"
        
        put_config = base_config.copy()
        put_config['option_type'] = 'put'
        put_config['strike_price'] = S * 0.95   # 5% OTM put
        put_config['name'] = f"Strangle Put - {base_config.get('ticker', 'Stock')}"
        
        configs = [call_config, put_config]
    
    elif strategy_type.lower() == 'spread':
        # Bull call spread: buy lower strike, sell higher strike
        long_config = base_config.copy()
        long_config['option_type'] = 'call'
        long_config['strike_price'] = S * 0.98   # Slightly ITM
        long_config['name'] = f"Spread Long Call - {base_config.get('ticker', 'Stock')}"
        
        short_config = base_config.copy()
        short_config['option_type'] = 'call'
        short_config['strike_price'] = S * 1.05  # OTM
        short_config['name'] = f"Spread Short Call - {base_config.get('ticker', 'Stock')}"
        
        configs = [long_config, short_config]
    
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")
    
    return configs


def merge_configs(configs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge multiple configurations into a single structure.
    
    Parameters:
    -----------
    configs : List[Dict[str, Any]]
        List of option configurations
    
    Returns:
    --------
    Dict[str, Any]
        Merged configuration with 'configurations' list
    """
    return {
        'configurations': configs,
        'simulation_settings': {
            'time_points': 20,
            'price_scenarios': {
                'min_percentage': 0.7,
                'max_percentage': 1.3,
                'num_points': 25
            },
            'volatility_scenarios': {
                'min_vol': 0.1,
                'max_vol': 0.8,
                'num_points': 10
            }
        },
        'created_at': datetime.now().isoformat()
    }
