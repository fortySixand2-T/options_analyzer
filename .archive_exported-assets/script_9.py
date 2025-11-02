
# Create a quick start guide
quick_start = """
╔═══════════════════════════════════════════════════════════════════════╗
║                 OPTIONS PRICING PIPELINE - QUICK START                ║
╚═══════════════════════════════════════════════════════════════════════╝

WHAT YOU HAVE:
==============
✓ Complete Python implementation (options_pricing_pipeline.py)
✓ Black-Scholes pricing engine
✓ Full Greeks calculations (Delta, Gamma, Theta, Vega, Rho)
✓ Time-based simulations
✓ Price scenario analysis
✓ JSON configuration system
✓ Example configurations and data
✓ Comprehensive documentation


STEP 1: BASIC USAGE
===================

import json
from options_pricing_pipeline import OptionsPricingPipeline
from datetime import datetime

# Initialize
pipeline = OptionsPricingPipeline()

# Create config
config = {
    "ticker": "AAPL",
    "current_price": 175.0,
    "strike_price": 180.0,
    "expiration_date": "2025-11-21",
    "option_type": "call",
    "implied_volatility": 0.30,
    "risk_free_rate": 0.045
}

# Calculate price
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

print(f"Option Price: ${price:.2f}")


STEP 2: GET GREEKS
==================

greeks = pipeline.calculate_greeks(
    S=175.0, K=180.0, T=T, r=0.045, sigma=0.30, option_type='call'
)

print("Greeks:")
for greek, value in greeks.items():
    print(f"  {greek}: {value:.6f}")


STEP 3: RUN SIMULATIONS
=======================

# Time simulation
time_sim = pipeline.simulate_price_over_time(config, time_points=20)
time_sim.to_csv('my_time_simulation.csv', index=False)

# Price scenarios
price_sim = pipeline.simulate_price_scenarios(
    config, 
    price_range=(150, 200), 
    num_prices=25
)
price_sim.to_csv('my_price_scenarios.csv', index=False)


STEP 4: USE JSON CONFIGS
=========================

# Save your config
with open('my_config.json', 'w') as f:
    json.dump(config, f, indent=2)

# Load it later
loaded_config = pipeline.load_config_from_file('my_config.json')


KEY PARAMETERS EXPLAINED:
=========================

current_price:       Current stock price ($)
strike_price:        Option strike price ($)
expiration_date:     Format: "YYYY-MM-DD"
option_type:         "call" or "put"
implied_volatility:  Annual volatility (0.30 = 30%)
risk_free_rate:      Annual rate (0.045 = 4.5%)


UNDERSTANDING GREEKS:
=====================

Delta (Δ):  Price change per $1 move in stock
            Range: 0 to 1 (calls), -1 to 0 (puts)
            Example: Δ=0.40 → $0.40 gain per $1 stock rise

Gamma (Γ):  Delta change per $1 move in stock
            Highest for at-the-money options
            Risk management metric

Theta (Θ):  Time decay per day (negative for long)
            Accelerates near expiration
            Example: Θ=-0.10 → loses $0.10/day

Vega (ν):   Price change per 1% IV change
            Example: ν=0.20 → $0.20 gain per 1% IV rise

Rho (ρ):    Price change per 1% rate change
            Less important for short-term options


PRACTICAL EXAMPLES:
===================

1. Track weekly decay:
   time_sim = pipeline.simulate_price_over_time(config, time_points=4)

2. Analyze around strike:
   price_sim = pipeline.simulate_price_scenarios(
       config, price_range=(175, 185), num_prices=20
   )

3. Compare volatility scenarios:
   for iv in [0.20, 0.30, 0.40, 0.50]:
       config['implied_volatility'] = iv
       price = pipeline.black_scholes_price(...)


FILES INCLUDED:
===============

options_pricing_pipeline.py    → Main Python script
option_configs.json            → Example configurations
README.md                      → Full documentation
USAGE_GUIDE.txt               → Detailed usage guide
option_price_time_simulation.csv     → Sample output
option_price_scenarios.csv           → Sample output


NEXT STEPS:
===========

1. Modify the sample config with your own ticker/parameters
2. Run simulations to see price and Greeks evolution
3. Export results to CSV for analysis
4. Build your own strategies using the Greeks
5. Integrate with real-time data sources (Alpha Vantage, etc.)


TIPS FOR YOUR USE CASE:
=======================

✓ Store your configurations in JSON for easy reuse
✓ Set Greeks values by using implied_volatility parameter
✓ Run time simulations to see theta decay patterns
✓ Use price scenarios to find optimal entry/exit points
✓ Compare scenarios side-by-side with different IV levels
✓ Export to CSV and analyze in Excel/Python/R


SUPPORT:
========

- Check README.md for full API reference
- Review USAGE_GUIDE.txt for detailed examples
- Examine option_configs.json for configuration templates
- Study the sample CSV outputs for data structure


═══════════════════════════════════════════════════════════════════════
Built with: NumPy, Pandas, SciPy
Based on: Black-Scholes Model (1973)
Version: 1.0.0 | October 2025
═══════════════════════════════════════════════════════════════════════
"""

print(quick_start)

# Save quick start
with open('QUICK_START.txt', 'w') as f:
    f.write(quick_start)

print("\n✓ Quick start guide saved to 'QUICK_START.txt'")
