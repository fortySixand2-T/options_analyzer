import pandas as pd
import plotly.graph_objects as go
from sklearn.preprocessing import MinMaxScaler
import numpy as np

# Load the data
df = pd.read_csv('option_price_scenarios.csv')

# Sort by underlying price to ensure proper line connections
df = df.sort_values('Underlying_Price')

# Create normalization for Gamma and Vega to scale them to 0-1 range like Delta
scaler_gamma = MinMaxScaler()
scaler_vega = MinMaxScaler()

# Normalize Gamma and Vega to 0-1 range
df['Gamma_Norm'] = scaler_gamma.fit_transform(df[['Gamma']]).flatten()
df['Vega_Norm'] = scaler_vega.fit_transform(df[['Vega']]).flatten()

# Create the figure
fig = go.Figure()

# Add Delta line (already in 0-1 range)
fig.add_trace(go.Scatter(
    x=df['Underlying_Price'],
    y=df['Delta'],
    mode='lines+markers',
    name='Delta',
    line=dict(color='#1FB8CD', width=3),
    marker=dict(size=6)
))

# Add normalized Gamma line
fig.add_trace(go.Scatter(
    x=df['Underlying_Price'],
    y=df['Gamma_Norm'],
    mode='lines+markers',
    name='Gamma (Norm)',
    line=dict(color='#DB4545', width=3),
    marker=dict(size=6)
))

# Add normalized Vega line
fig.add_trace(go.Scatter(
    x=df['Underlying_Price'],
    y=df['Vega_Norm'],
    mode='lines+markers',
    name='Vega (Norm)',
    line=dict(color='#2E8B57', width=3),
    marker=dict(size=6)
))

# Update layout
fig.update_layout(
    title='Option Greeks vs Underlying Prices',
    xaxis_title='Underlying Price',
    yaxis_title='Normalized Value',
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='center', x=0.5)
)

# Update y-axis to show 0-1 range clearly
fig.update_yaxes(range=[0, 1])

# Update traces for better visibility
fig.update_traces(cliponaxis=False)

# Save as both PNG and SVG
fig.write_image('option_greeks_chart.png')
fig.write_image('option_greeks_chart.svg', format='svg')

print("Chart created successfully!")
print(f"Underlying prices range: {df['Underlying_Price'].min()} to {df['Underlying_Price'].max()}")
print(f"Delta range: {df['Delta'].min():.6f} to {df['Delta'].max():.6f}")
print(f"Original Gamma range: {df['Gamma'].min():.6f} to {df['Gamma'].max():.6f}")
print(f"Original Vega range: {df['Vega'].min():.6f} to {df['Vega'].max():.6f}")