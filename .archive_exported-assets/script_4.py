
# Example 4: Advanced simulation with custom Greeks
# This shows how to use the pipeline with user-defined Greek values

print("\nEXAMPLE 3: Advanced Simulation with Multiple Scenarios")
print("="*60)

# Create multiple configurations to compare
scenarios = [
    {
        "name": "Low Volatility",
        "ticker": "AAPL",
        "current_price": 175.0,
        "strike_price": 180.0,
        "expiration_date": "2025-11-21",
        "option_type": "call",
        "implied_volatility": 0.20,  # 20% IV
        "risk_free_rate": 0.045
    },
    {
        "name": "Medium Volatility",
        "ticker": "AAPL",
        "current_price": 175.0,
        "strike_price": 180.0,
        "expiration_date": "2025-11-21",
        "option_type": "call",
        "implied_volatility": 0.30,  # 30% IV
        "risk_free_rate": 0.045
    },
    {
        "name": "High Volatility",
        "ticker": "AAPL",
        "current_price": 175.0,
        "strike_price": 180.0,
        "expiration_date": "2025-11-21",
        "option_type": "call",
        "implied_volatility": 0.50,  # 50% IV
        "risk_free_rate": 0.045
    }
]

comparison_results = []

for scenario in scenarios:
    T = (datetime.strptime(scenario['expiration_date'], '%Y-%m-%d') - datetime.now()).days / 365.0
    
    price = pipeline.black_scholes_price(
        S=scenario['current_price'],
        K=scenario['strike_price'],
        T=T,
        r=scenario['risk_free_rate'],
        sigma=scenario['implied_volatility'],
        option_type=scenario['option_type']
    )
    
    greeks = pipeline.calculate_greeks(
        S=scenario['current_price'],
        K=scenario['strike_price'],
        T=T,
        r=scenario['risk_free_rate'],
        sigma=scenario['implied_volatility'],
        option_type=scenario['option_type']
    )
    
    result = {
        'Scenario': scenario['name'],
        'IV': scenario['implied_volatility'],
        'Option_Price': price,
        **greeks
    }
    comparison_results.append(result)

comparison_df = pd.DataFrame(comparison_results)
print(comparison_df.to_string(index=False))

print("\n" + "="*60)
print("Key Insights:")
print(f"  • Low IV ({scenarios[0]['implied_volatility']}) → Price: ${comparison_results[0]['Option_Price']:.2f}")
print(f"  • Med IV ({scenarios[1]['implied_volatility']}) → Price: ${comparison_results[1]['Option_Price']:.2f}")
print(f"  • High IV ({scenarios[2]['implied_volatility']}) → Price: ${comparison_results[2]['Option_Price']:.2f}")
print(f"\n  Higher volatility increases option value due to greater potential for profitable moves")
