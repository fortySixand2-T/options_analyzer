import pandas as pd
import plotly.graph_objects as go

# Load the data
df = pd.read_csv('option_price_scenarios.csv')

# Create the line chart
fig = go.Figure()

# Add Option Price line
fig.add_trace(go.Scatter(
    x=df['Underlying_Price'],
    y=df['Option_Price'],
    mode='lines',
    name='Option Price',
    line=dict(color='#1FB8CD', width=3),
    hovertemplate='Price: $%{x}<br>Option: $%{y:.2f}<extra></extra>'
))

# Add Intrinsic Value line
fig.add_trace(go.Scatter(
    x=df['Underlying_Price'],
    y=df['Intrinsic_Value'],
    mode='lines',
    name='Intrinsic Val',
    line=dict(color='#DB4545', width=3),
    hovertemplate='Price: $%{x}<br>Intrinsic: $%{y:.2f}<extra></extra>'
))

# Update layout
fig.update_layout(
    title='Option Price vs Underlying Price',
    xaxis_title='Stock Price ($)',
    yaxis_title='Value ($)',
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='center', x=0.5)
)

# Update traces
fig.update_traces(cliponaxis=False)

# Save as both PNG and SVG
fig.write_image('option_chart.png')
fig.write_image('option_chart.svg', format='svg')

fig.show()