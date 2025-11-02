import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Load the data
df = pd.read_csv('option_price_time_simulation.csv')

# Create line chart showing Delta evolution over time
fig = px.line(df, 
              x='Days_to_Expiration', 
              y='Delta',
              title='Delta Evolution as Expiration Approaches')

# Update traces
fig.update_traces(cliponaxis=False)

# Update layout with axis labels (keeping under 15 characters)
fig.update_layout(
    xaxis_title='Days to Exp',
    yaxis_title='Delta'
)

# Update x-axis to show the progression from 30 days to 0 days
fig.update_xaxes(autorange='reversed')

# Save as both PNG and SVG
fig.write_image('chart.png')
fig.write_image('chart.svg', format='svg')

print("Chart saved successfully as chart.png and chart.svg")