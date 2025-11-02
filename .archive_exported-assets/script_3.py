
# Example 3: Simulate option prices across different underlying prices
print("\nSIMULATION 2: Price Scenarios Across Different Underlying Prices")
print("="*60)

price_scenarios = pipeline.simulate_price_scenarios(config, num_prices=15)

# Display results
display_cols = ['Underlying_Price', 'Option_Price', 'Moneyness', 'Intrinsic_Value', 
                'Delta', 'Gamma', 'Vega']
print(price_scenarios[display_cols].to_string(index=False))

# Save to CSV
price_scenarios.to_csv('option_price_scenarios.csv', index=False)
print("\n✓ Full simulation saved to 'option_price_scenarios.csv'")
