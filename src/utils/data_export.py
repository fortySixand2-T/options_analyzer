#!/usr/bin/env python3
"""
Data Export Utilities
=====================

Provides functions for exporting simulation results to various formats.

Author: Restructured Options Pricing System
Date: October 2025
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Union, Optional
from datetime import datetime
import json


def export_to_csv(df: pd.DataFrame, file_path: Union[str, Path], 
                  include_timestamp: bool = True) -> str:
    """
    Export DataFrame to CSV file.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Data to export
    file_path : Union[str, Path]
        Path for the CSV file
    include_timestamp : bool
        Whether to include timestamp in filename
    
    Returns:
    --------
    str
        Full path of the exported file
    """
    file_path = Path(file_path)
    
    if include_timestamp:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        stem = file_path.stem
        suffix = file_path.suffix
        file_path = file_path.parent / f"{stem}_{timestamp}{suffix}"
    
    df.to_csv(file_path, index=False)
    print(f"Data exported to: {file_path}")
    return str(file_path)


def export_to_excel(df: pd.DataFrame, file_path: Union[str, Path],
                   sheet_name: str = 'Results', include_timestamp: bool = True) -> str:
    """
    Export DataFrame to Excel file.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Data to export
    file_path : Union[str, Path]
        Path for the Excel file
    sheet_name : str
        Name of the worksheet
    include_timestamp : bool
        Whether to include timestamp in filename
    
    Returns:
    --------
    str
        Full path of the exported file
    """
    file_path = Path(file_path)
    
    if include_timestamp:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        stem = file_path.stem
        suffix = file_path.suffix
        file_path = file_path.parent / f"{stem}_{timestamp}{suffix}"
    
    with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    print(f"Data exported to: {file_path}")
    return str(file_path)


def export_multiple_sheets(data_dict: Dict[str, pd.DataFrame], file_path: Union[str, Path],
                          include_timestamp: bool = True) -> str:
    """
    Export multiple DataFrames to separate Excel sheets.
    
    Parameters:
    -----------
    data_dict : Dict[str, pd.DataFrame]
        Dictionary with sheet names as keys and DataFrames as values
    file_path : Union[str, Path]
        Path for the Excel file
    include_timestamp : bool
        Whether to include timestamp in filename
    
    Returns:
    --------
    str
        Full path of the exported file
    """
    file_path = Path(file_path)
    
    if include_timestamp:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        stem = file_path.stem
        suffix = file_path.suffix
        file_path = file_path.parent / f"{stem}_{timestamp}{suffix}"
    
    with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
        for sheet_name, df in data_dict.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    print(f"Multi-sheet data exported to: {file_path}")
    return str(file_path)


def export_summary_report(config: Dict, time_df: pd.DataFrame, price_df: pd.DataFrame,
                         file_path: Union[str, Path]) -> str:
    """
    Export a comprehensive summary report to Excel.
    
    Parameters:
    -----------
    config : Dict
        Option configuration
    time_df : pd.DataFrame
        Time simulation results
    price_df : pd.DataFrame
        Price scenario results
    file_path : Union[str, Path]
        Path for the Excel file
    
    Returns:
    --------
    str
        Full path of the exported file
    """
    file_path = Path(file_path)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    stem = file_path.stem
    suffix = file_path.suffix
    file_path = file_path.parent / f"{stem}_{timestamp}{suffix}"
    
    # Create summary statistics
    current_price = time_df.iloc[0]['Option_Price'] if not time_df.empty else 0
    expiry_value = time_df.iloc[-1]['Intrinsic_Value'] if not time_df.empty else 0
    max_time_value = time_df['Time_Value'].max() if not time_df.empty else 0
    
    summary_data = {
        'Parameter': ['Ticker', 'Current Stock Price', 'Strike Price', 'Option Type', 
                     'Expiration Date', 'Implied Volatility', 'Current Option Price',
                     'Expiry Intrinsic Value', 'Max Time Value'],
        'Value': [config.get('ticker', 'N/A'),
                 config.get('current_price', 'N/A'),
                 config.get('strike_price', 'N/A'),
                 config.get('option_type', 'N/A').title(),
                 config.get('expiration_date', 'N/A'),
                 f"{config.get('implied_volatility', 0)*100:.1f}%",
                 f"${current_price:.2f}",
                 f"${expiry_value:.2f}",
                 f"${max_time_value:.2f}"]
    }
    summary_df = pd.DataFrame(summary_data)
    
    # Create data dictionary
    data_dict = {
        'Summary': summary_df,
        'Time_Analysis': time_df,
        'Price_Scenarios': price_df
    }
    
    with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
        for sheet_name, df in data_dict.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    print(f"Summary report exported to: {file_path}")
    return str(file_path)


def export_to_json( data: Union[Dict, List, pd.DataFrame], file_path: Union[str, Path], include_timestamp: bool = True) -> str:
    """
    Export data to JSON file.
    
    Parameters:
    -----------
    data : Union[Dict, List, pd.DataFrame]
        Data to export
    file_path : Union[str, Path]
        Path for the JSON file
    include_timestamp : bool
        Whether to include timestamp in filename
    
    Returns:
    --------
    str
        Full path of the exported file
    """
    file_path = Path(file_path)
    
    if include_timestamp:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        stem = file_path.stem
        suffix = file_path.suffix
        file_path = file_path.parent / f"{stem}_{timestamp}{suffix}"
    
    # Convert DataFrame to dict if needed
    if isinstance(data, pd.DataFrame):
        data = data.to_dict(orient='records')
    
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    
    print(f"Data exported to JSON: {file_path}")
    return str(file_path)


def create_export_directory(base_path: Union[str, Path], config: Dict) -> Path:
    """
    Create organized export directory structure.
    
    Parameters:
    -----------
    base_path : Union[str, Path]
        Base directory for exports
    config : Dict
        Option configuration for directory naming
    
    Returns:
    --------
    Path
        Created directory path
    """
    base_path = Path(base_path)
    
    # Create directory name based on config
    ticker = config.get('ticker', 'UNKNOWN')
    option_type = config.get('option_type', 'option')
    strike = config.get('strike_price', 0)
    exp_date = config.get('expiration_date', 'unknown')
    
    dir_name = f"{ticker}_{option_type}_{strike}_{exp_date}"
    export_dir = base_path / dir_name
    
    # Create directory if it doesn't exist
    export_dir.mkdir(parents=True, exist_ok=True)
    
    return export_dir


def bulk_export(results: Dict[str, pd.DataFrame], config: Dict, 
                export_dir: Union[str, Path], formats: List[str] = ['csv', 'excel']) -> Dict[str, str]:
    """
    Export multiple results in various formats.
    
    Parameters:
    -----------
    results : Dict[str, pd.DataFrame]
        Dictionary of results to export
    config : Dict
        Option configuration
    export_dir : Union[str, Path]
        Directory for exports
    formats : List[str]
        List of formats to export ('csv', 'excel', 'json')
    
    Returns:
    --------
    Dict[str, str]
        Dictionary mapping result names to exported file paths
    """
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    
    exported_files = {}
    
    for result_name, df in results.items():
        file_base = f"{config.get('ticker', 'option')}_{result_name}"
        
        if 'csv' in formats:
            csv_path = export_to_csv(df, export_dir / f"{file_base}.csv")
            exported_files[f"{result_name}_csv"] = csv_path
        
        if 'excel' in formats:
            excel_path = export_to_excel(df, export_dir / f"{file_base}.xlsx")
            exported_files[f"{result_name}_excel"] = excel_path
        
        if 'json' in formats:
            json_path = export_to_json(df, export_dir / f"{file_base}.json")
            exported_files[f"{result_name}_json"] = json_path
    
    return exported_files
