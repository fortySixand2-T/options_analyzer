import pandas as pd
import plotly.graph_objects as go

# Load the data
df = pd.read_csv('option_price_time_simulation.csv')

# Create the line chart
fig = go.Figure()

# Add Option Price line
fig.add_trace(go.Scatter(
    x=df['Days_to_Expiration'],
    y=df['Option_Price'],
    mode='lines',
    name='Option Price',
    line=dict(color='#1FB8CD', width=3)
))

# Add Time Value line (with slight offset for visibility since they overlap)
fig.add_trace(go.Scatter(
    x=df['Days_to_Expiration'],
    y=df['Time_Value'],
    mode='lines',
    name='Time Value',
    line=dict(color='#DB4545', width=3, dash='dot')
))

# Update layout with exact title from instructions
fig.update_layout(
    title='Option Price Decay Over Time (Time to Expiration)',
    xaxis_title='Days to Expiration',
    yaxis_title='Price ($)',
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='center', x=0.5)
)

# Update traces for better visualization
fig.update_traces(cliponaxis=False)

# Save as both PNG and SVG
fig.write_image('option_price_decay.png')
fig.write_image('option_price_decay.svg', format='svg')

fig.show()