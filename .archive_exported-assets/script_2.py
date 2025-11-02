
# Example 2: Simulate option price evolution over time
print("SIMULATION 1: Price Evolution Over Time")
print("="*60)

time_simulation = pipeline.simulate_price_over_time(config, time_points=15)

# Display key columns
display_cols = ['Date', 'Days_to_Expiration', 'Option_Price', 'Time_Value', 
                'Delta', 'Gamma', 'Theta', 'Vega']
print(time_simulation[display_cols].to_string(index=False))

# Save to CSV
time_simulation.to_csv('option_price_time_simulation.csv', index=False)
print("\n✓ Full simulation saved to 'option_price_time_simulation.csv'")
