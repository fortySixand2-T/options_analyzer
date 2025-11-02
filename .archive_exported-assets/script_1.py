
# Example 1: Create a sample configuration in JSON format
sample_config = {
    "ticker": "AAPL",
    "current_price": 175.0,
    "strike_price": 180.0,
    "expiration_date": "2025-11-21",  # 1 month from now
    "option_type": "call",
    "implied_volatility": 0.30,  # 30% IV
    "risk_free_rate": 0.045  # 4.5% annual
}

# Convert to JSON string
json_config = json.dumps(sample_config, indent=2)
print("Sample JSON Configuration:")
print(json_config)
print("\n" + "="*60 + "\n")

# Load and use the configuration
config = pipeline.load_config_from_json(json_config)

# Calculate current option price
current_T = (datetime.strptime(config['expiration_date'], '%Y-%m-%d') - datetime.now()).days / 365.0
current_price = pipeline.black_scholes_price(
    S=config['current_price'],
    K=config['strike_price'],
    T=current_T,
    r=config['risk_free_rate'],
    sigma=config['implied_volatility'],
    option_type=config['option_type']
)

print(f"Current Option Price: ${current_price:.2f}")

# Calculate Greeks
greeks = pipeline.calculate_greeks(
    S=config['current_price'],
    K=config['strike_price'],
    T=current_T,
    r=config['risk_free_rate'],
    sigma=config['implied_volatility'],
    option_type=config['option_type']
)

print("\nGreeks:")
for greek, value in greeks.items():
    print(f"  {greek:8s}: {value:10.6f}")
