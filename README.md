# Modular Options Pricing System

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A comprehensive, modular Python system for options pricing and analysis using the Black-Scholes model. Designed for traders, analysts, and researchers who need robust options analytics with clean, extensible code.

## 🚀 Features

### Core Pricing Engine
- **Black-Scholes Model**: Accurate European option pricing for calls and puts
- **Complete Greeks Suite**: Delta, Gamma, Theta, Vega, and Rho calculations
- **Modular Architecture**: Clean separation of pricing, analytics, and utilities

### Advanced Analytics
- **Time Decay Analysis**: Track option value evolution from purchase to expiration
- **Price Scenario Modeling**: Analyze P&L across different underlying prices
- **Volatility Sensitivity**: Study option behavior under various IV conditions
- **Strategy Comparison**: Compare multiple options strategies side-by-side

### Visualization & Export
- **Professional Charts**: matplotlib-based visualizations for all analyses
- **Multi-format Export**: CSV, Excel, JSON export capabilities
- **Summary Reports**: Comprehensive analysis reports with key metrics

### User-Friendly Interface
- **High-level API**: Simple `OptionsAnalyzer` class for complete analysis
- **Configuration Management**: JSON/YAML-based option configurations
- **Extensive Examples**: Usage examples from basic to advanced strategies

## 📁 Project Structure

```
options/
├── src/                          # Core source code
│   ├── models/                   # Pricing models
│   │   ├── black_scholes.py     # Black-Scholes implementation
│   │   └── __init__.py
│   ├── analytics/               # Analysis and simulation
│   │   ├── simulations.py       # Scenario simulations
│   │   ├── visualization.py     # Plotting functions
│   │   └── __init__.py
│   ├── utils/                   # Utilities
│   │   ├── config.py           # Configuration management
│   │   ├── data_export.py      # Data export functions
│   │   └── __init__.py
│   ├── options_analyzer.py      # High-level interface
│   └── __init__.py             # Main package
├── config/                      # Configuration files
│   └── option_configs.json     # Example configurations
├── examples/                    # Usage examples
│   ├── basic_usage.py          # Basic examples
│   └── advanced_strategies.py  # Complex strategies
├── tests/                       # Unit tests
├── requirements.txt            # Dependencies
└── README.md                   # This file
```

## 🛠 Installation

### Prerequisites
- Python 3.8 or higher
- pip package manager

### Install Dependencies

```bash
# Navigate to the options directory
cd /path/to/options

# Install required packages
pip install -r requirements.txt
```

### Optional: Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## 🎯 Quick Start

### Basic Option Pricing

```python
from src.options_analyzer import OptionsAnalyzer

# Define your option
config = {
    'ticker': 'AAPL',
    'current_price': 175.0,
    'strike_price': 180.0,
    'expiration_date': '2025-12-20',
    'option_type': 'call',
    'implied_volatility': 0.25
}

# Create analyzer
analyzer = OptionsAnalyzer(config)

# Get current price and Greeks
print(f"Option Price: ${analyzer.get_current_price():.2f}")
print(f"Greeks: {analyzer.get_greeks()}")

# Print comprehensive summary
analyzer.print_summary()
```

### Complete Analysis with Export

```python
# Run full analysis with visualizations and data export
results = analyzer.run_full_analysis(export_results=True)

# This creates:
# - Time decay analysis
# - Price scenario analysis  
# - Volatility sensitivity analysis
# - Professional charts
# - Excel summary report
# - CSV data exports
```

## 📊 Usage Examples

### 1. Time Decay Analysis

Study how your option loses value as expiration approaches:

```python
# Analyze time decay over 20 time points
time_df = analyzer.analyze_time_decay(time_points=20)

# View key columns
print(time_df[['Days_to_Expiration', 'Option_Price', 'Theta']])
```

### 2. Price Scenario Modeling

Understand P&L at different stock prices:

```python
# Analyze across price range
price_df = analyzer.analyze_price_scenarios(
    price_range=(150, 200),
    num_prices=25
)

# Find break-even point
break_even = config['strike_price'] + price_df.iloc[0]['Option_Price']
print(f"Break-even: ${break_even:.2f}")
```

### 3. Advanced Strategies

Analyze complex multi-leg strategies:

```python
from src.utils.config import create_strategy_configs

# Create Iron Condor configuration
configs = create_strategy_configs(base_config, 'iron_condor')

# Analyze each leg
for config in configs:
    leg_analyzer = OptionsAnalyzer(config)
    print(f"{config['name']}: ${leg_analyzer.get_current_price():.2f}")
```

## 🔧 Modular Components

### Models Package (`src/models/`)

**Pure pricing functions** - no side effects, easy to test:

```python
from src.models import black_scholes_price, calculate_greeks

price = black_scholes_price(S=100, K=105, T=0.25, r=0.05, sigma=0.20)
greeks = calculate_greeks(S=100, K=105, T=0.25, r=0.05, sigma=0.20)
```

### Analytics Package (`src/analytics/`)

**Simulation and visualization functions**:

```python
from src.analytics import simulate_price_over_time, plot_price_evolution

# Run simulation
results = simulate_price_over_time(config, time_points=30)

# Create visualization
fig = plot_price_evolution(results)
fig.savefig('time_decay.png')
```

### Utils Package (`src/utils/`)

**Configuration and data management**:

```python
from src.utils import load_config_from_json, export_to_csv

# Load configuration
config = load_config_from_json('config/my_options.json')

# Export results
export_to_csv(results_df, 'analysis_results.csv')
```

## 📈 Supported Strategies

- **Single Options**: Calls, Puts, ATM, ITM, OTM analysis
- **Spreads**: Bull/Bear call spreads, put spreads
- **Straddles/Strangles**: Long/short volatility plays
- **Iron Condors**: Limited risk/reward strategies
- **Custom Combinations**: Any multi-leg strategy

## 🎨 Visualization Capabilities

- **Price Evolution Charts**: Time decay visualization
- **P&L Diagrams**: Profit/loss across price ranges
- **Greeks Surface Plots**: Multi-dimensional risk analysis
- **Strategy Comparisons**: Side-by-side analysis
- **Volatility Surfaces**: IV sensitivity analysis

## 📋 Configuration Format

### JSON Configuration
```json
{
  "ticker": "AAPL",
  "current_price": 175.0,
  "strike_price": 180.0,
  "expiration_date": "2025-12-20",
  "option_type": "call",
  "implied_volatility": 0.25,
  "risk_free_rate": 0.045
}
```

### Required Fields
- `current_price`: Current stock price
- `strike_price`: Option strike price  
- `expiration_date`: Expiration date (YYYY-MM-DD)
- `option_type`: "call" or "put"
- `implied_volatility`: Annual volatility (decimal)

### Optional Fields
- `ticker`: Stock symbol
- `risk_free_rate`: Annual risk-free rate (default: 4.5%)
- `name`: Configuration name for identification

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest tests/ --cov=src/

# Run specific test file
python -m pytest tests/test_black_scholes.py -v
```

## 🚀 Running Examples

```bash
# Basic usage examples
cd examples
python basic_usage.py

# Advanced strategies
python advanced_strategies.py
```

## 📚 Greeks Explained

| Greek | Description | Use Case |
|-------|-------------|----------|
| **Delta** | Price sensitivity to underlying move | Hedge ratios, directional exposure |
| **Gamma** | Rate of Delta change | Risk management, position sizing |
| **Theta** | Time decay (per day) | Income strategies, time management |
| **Vega** | Volatility sensitivity | Volatility trading, earnings plays |
| **Rho** | Interest rate sensitivity | Long-term options, rate environment |

## 🔄 Migration from Old System

To migrate from the previous monolithic system:

1. **Replace imports**:
   ```python
   # Old
   from analysis import OptionsPricingPipeline
   
   # New  
   from src.options_analyzer import OptionsAnalyzer
   ```

2. **Update instantiation**:
   ```python
   # Old
   pipeline = OptionsPricingPipeline()
   
   # New
   analyzer = OptionsAnalyzer(config)
   ```

3. **Use new methods**:
   ```python
   # Old
   price = pipeline.black_scholes_price(S, K, T, r, sigma)
   
   # New
   price = analyzer.get_current_price()
   ```

## 🤝 Contributing

1. Follow PEP 8 style guidelines
2. Add unit tests for new features
3. Update documentation for changes
4. Use meaningful commit messages

## 📄 License

MIT License - see LICENSE file for details.

## 🆘 Support

For questions or issues:
1. Check the examples directory
2. Review the docstrings in source code
3. Create an issue with detailed description

---

**Built for traders who demand precision and developers who value clean code.**
