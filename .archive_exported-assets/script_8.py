
# Create a comprehensive README file
readme_content = """# Options Pricing Pipeline

A comprehensive Python tool for simulating option contract prices using the Black-Scholes model with full Greeks calculations.

## Features

- **Black-Scholes Pricing**: Accurate European option pricing for calls and puts
- **Complete Greeks**: Delta, Gamma, Theta, Vega, and Rho calculations
- **Time Simulations**: Track option price evolution from now to expiration
- **Price Scenarios**: Analyze option behavior across different underlying prices
- **JSON Configuration**: Easy-to-use JSON-based configuration system
- **CSV Export**: Save all simulation results to CSV files

## Installation

### Requirements

```bash
pip install numpy pandas scipy
```

### Quick Start

```python
from options_pricing_pipeline import OptionsPricingPipeline
from datetime import datetime

# Initialize
pipeline = OptionsPricingPipeline()

# Configure your option
config = {
    "ticker": "AAPL",
    "current_price": 175.0,
    "strike_price": 180.0,
    "expiration_date": "2025-11-21",
    "option_type": "call",
    "implied_volatility": 0.30,
    "risk_free_rate": 0.045
}

# Calculate price and Greeks
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
print(f"Delta: {greeks['Delta']:.4f}")
print(f"Theta: {greeks['Theta']:.4f}")
```

## Configuration Format

### JSON Configuration

```json
{
  "ticker": "AAPL",
  "current_price": 175.0,
  "strike_price": 180.0,
  "expiration_date": "2025-11-21",
  "option_type": "call",
  "implied_volatility": 0.30,
  "risk_free_rate": 0.045
}
```

### Parameters

- **ticker** (str): Stock ticker symbol
- **current_price** (float): Current underlying stock price
- **strike_price** (float): Option strike price
- **expiration_date** (str): Expiration date in YYYY-MM-DD format
- **option_type** (str): "call" or "put"
- **implied_volatility** (float): Annual volatility (0.30 = 30%)
- **risk_free_rate** (float): Annual risk-free rate (0.045 = 4.5%)

## Usage Examples

### 1. Time-Based Simulation

Simulate how option price and Greeks evolve over time:

```python
# Simulate 20 time points from now to expiration
time_simulation = pipeline.simulate_price_over_time(
    config=config,
    time_points=20
)

# Save results
time_simulation.to_csv('time_simulation.csv', index=False)

# View key metrics
print(time_simulation[['Days_to_Expiration', 'Option_Price', 'Delta', 'Theta']])
```

### 2. Price Scenario Analysis

Analyze option behavior across different underlying prices:

```python
# Simulate across price range
price_scenarios = pipeline.simulate_price_scenarios(
    config=config,
    price_range=(150, 200),  # Custom range
    num_prices=25
)

# Save results
price_scenarios.to_csv('price_scenarios.csv', index=False)

# View results
print(price_scenarios[['Underlying_Price', 'Option_Price', 'Delta', 'Gamma']])
```

### 3. Multiple Scenario Comparison

Compare different volatility scenarios:

```python
scenarios = [
    {"name": "Low IV", "implied_volatility": 0.20},
    {"name": "Med IV", "implied_volatility": 0.30},
    {"name": "High IV", "implied_volatility": 0.50}
]

results = []
for scenario in scenarios:
    config['implied_volatility'] = scenario['implied_volatility']
    price = pipeline.black_scholes_price(...)
    greeks = pipeline.calculate_greeks(...)
    results.append({
        'Scenario': scenario['name'],
        'Price': price,
        **greeks
    })

import pandas as pd
df = pd.DataFrame(results)
print(df)
```

## Greeks Explained

### Delta (Δ)
- **Range**: 0 to 1 for calls, -1 to 0 for puts
- **Meaning**: Change in option price per $1 change in underlying
- **Example**: Delta of 0.40 means option gains $0.40 when stock rises $1

### Gamma (Γ)
- **Meaning**: Change in Delta per $1 change in underlying
- **Highest**: At-the-money options
- **Use**: Risk management and position monitoring

### Theta (Θ)
- **Meaning**: Time decay per day (negative for long options)
- **Accelerates**: As expiration approaches
- **Example**: Theta of -0.10 means option loses $0.10 per day

### Vega (ν)
- **Meaning**: Change in option price per 1% change in implied volatility
- **Example**: Vega of 0.20 means option gains $0.20 if IV increases 1%
- **Important**: Earnings plays and volatility trading

### Rho (ρ)
- **Meaning**: Change in option price per 1% change in interest rate
- **Less Important**: For short-term options

## API Reference

### OptionsPricingPipeline

#### Methods

**`black_scholes_price(S, K, T, r, sigma, option_type)`**
- Calculate Black-Scholes option price
- Returns: float (option price)

**`calculate_greeks(S, K, T, r, sigma, option_type)`**
- Calculate all Greeks
- Returns: dict with Delta, Gamma, Theta, Vega, Rho

**`simulate_price_over_time(config, time_points)`**
- Simulate price evolution over time
- Returns: pandas DataFrame

**`simulate_price_scenarios(config, price_range, num_prices)`**
- Simulate across price scenarios
- Returns: pandas DataFrame

**`load_config_from_json(json_string)`**
- Load configuration from JSON string
- Returns: dict

**`load_config_from_file(filepath)`**
- Load configuration from JSON file
- Returns: dict

**`save_results_to_csv(df, filename)`**
- Save DataFrame to CSV
- Returns: None

## Output Files

### Time Simulation CSV
Contains: Date, Days_to_Expiration, Option_Price, Intrinsic_Value, Time_Value, Delta, Gamma, Theta, Vega, Rho

### Price Scenarios CSV
Contains: Underlying_Price, Option_Price, Moneyness, Intrinsic_Value, Delta, Gamma, Theta, Vega, Rho

## Advanced Usage

### Custom Time Points

```python
from datetime import datetime, timedelta

custom_dates = [
    datetime.now(),
    datetime.now() + timedelta(days=7),
    datetime.now() + timedelta(days=14),
    datetime.now() + timedelta(days=21),
    datetime.now() + timedelta(days=30)
]

results = pipeline.simulate_price_over_time(
    config=config,
    time_points=custom_dates
)
```

### Loading from JSON File

```python
# Load configuration from file
config = pipeline.load_config_from_file('my_config.json')

# Run simulations
time_sim = pipeline.simulate_price_over_time(config)
```

## Mathematical Background

The pipeline uses the Black-Scholes model for European options:

**Call Price:**
```
C = S * N(d1) - K * e^(-rT) * N(d2)
```

**Put Price:**
```
P = K * e^(-rT) * N(-d2) - S * N(-d1)
```

Where:
```
d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T)
d2 = d1 - σ√T
```

## Practical Tips

1. **Implied Volatility**: Higher IV → higher option prices
2. **Time Decay**: Accelerates non-linearly near expiration
3. **ATM Options**: Highest Gamma and Vega sensitivity
4. **Delta Hedging**: Use Delta for position hedging
5. **Vega Trading**: Important for earnings and events

## Limitations

- European options only (no early exercise)
- Constant volatility assumption
- Constant interest rate
- No dividends (can be extended)
- Assumes log-normal price distribution

## License

MIT License - Free to use and modify

## Contributing

Contributions welcome! Please submit pull requests or open issues.

## Author

Created for options trading analysis and education.

## Version

1.0.0 - October 2025
"""

# Save README
with open('README.md', 'w') as f:
    f.write(readme_content)

print("✓ Comprehensive README.md created")
print("\nAll files created:")
print("  1. options_pricing_pipeline.py - Main Python script")
print("  2. option_configs.json - Example JSON configuration")
print("  3. USAGE_GUIDE.txt - Detailed usage guide")
print("  4. README.md - Full documentation")
print("  5. option_price_time_simulation.csv - Sample time simulation")
print("  6. option_price_scenarios.csv - Sample price scenarios")
