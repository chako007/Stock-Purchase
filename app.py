import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# --- PAGE SETUP ---
st.set_page_config(page_title="Hotel Benhur Liquor Order", layout="wide")
st.title("🥃 Rocks & Brews: Purchase Order Generator")
st.write("Upload your Closing Stock and Sales reports (XLSX or XLS) to instantly calculate your next liquor order.")

# --- SIDEBAR: HARDCODED LISTS ---
st.sidebar.header("⚙️ Configuration")
st.sidebar.write("If you get new brands, add them here so the math calculates correctly.")

bottles_1L_input = st.sidebar.text_area("1-Litre Pouring Bottles", value="BIG BROTHER\nGLENGARRY", height=100)
bottles_700ml_input = st.sidebar.text_area("700ml Bottles", value="JAGERMEISTER", height=100)

bottles_1L = [b.strip().upper() for b in bottles_1L_input.split('\n') if b.strip()]
bottles_700ml = [b.strip().upper() for b in bottles_700ml_input.split('\n') if b.strip()]

# --- MAIN UI: FILE UPLOADS ---
col1, col2 = st.columns(2)
with col1:
    stock_file = st.file_uploader("1. Upload Stock File", type=['xlsx', 'xls'])
with col2:
    sales_file = st.file_uploader("2. Upload Sales File", type=['xlsx', 'xls'])

# --- CORE LOGIC ---
def load_smart_excel(file_obj):
    df = pd.read_excel(file_obj, header=None)
    
    header_idx = 0
    for idx, row in df.iterrows():
        if row.astype(str).str.contains('Name', case=False, na=False).any():
            header_idx = idx
            break
            
    df.columns = df.iloc[header_idx].astype(str).str.strip()
    df_clean = df.iloc[header_idx + 1:].reset_index(drop=True)
    return df_clean

def process_and_filter_data(df):
    sizes = ['1l', '750', '500', '375', '180', '60']
    actual_cols = {}
    
    for size in sizes:
        matching_cols = [c for c in df.columns if str(c).lower().replace(" ", "").startswith(size)]
        actual_cols[size] = matching_cols[-1] if matching_cols else None

    col_60 = actual_cols['60']
    if not col_60:
        return pd.DataFrame()
    
    category_mask = df[col_60].isna() & df['Name'].notna()
    df.loc[category_mask, 'Category'] = df.loc[category_mask, 'Name']
    df['Category'] = df['Category'].ffill()
    
    df = df.dropna(subset=['Name', col_60])
    df['Name'] = df['Name'].astype(str).str.strip()
    df['Category'] = df['Category'].astype(str).str.strip().str.upper()
    df = df[~df['Name'].isin(['nan', 'NaN', '', 'None'])]
    
    allowed_liquor = ['WHISKY', 'BRANDY', 'RUM', 'GIN', 'VODKA', 'WINE', 'BEER']
    pattern_str = '|'.join(allowed_liquor)
    df = df[df['Category'].str.contains(pattern_str, case=False, na=False)]
    
    df_clean = df.copy() 
    for size in sizes:
        target_col = actual_cols[size]
        if target_col and target_col in df_clean.columns:
            df_clean[size] = pd.to_numeric(df_clean[target_col], errors='coerce').fillna(0).abs()
        else:
            df_clean[size] = 0.0
            
    agg_dict = {size: 'sum' for size in sizes}
    if 'Original_Order' in df_clean.columns:
        agg_dict['Original_Order'] = 'min'
        
    df_grouped = df_clean.groupby(['Name', 'Category'], as_index=False).agg(agg_dict)
    return df_grouped

def custom_round(x):
    if pd.isna(x): return 0
    sign = 1 if x >= 0 else -1
    abs_x = abs(x)
    if abs_x - int(abs_x) > 0.5:
        return int(abs_x + 1) * sign
    else:
        return int(abs_x) * sign

# --- EXECUTION ---
if stock_file and sales_file:
    if st.button("Generate Purchase Order", type="primary"):
        with st.spinner("Calculating inventory..."):
            
            stock_df = load_smart_excel(stock_file)
            sales_df = load_smart_excel(sales_file)
            
            stock_df['Original_Order'] = range(len(stock_df))
            
            stock_df_clean = process_and_filter_data(stock_df)
            sales_df_clean = process_and_filter_data(sales_df)
            
            # Alias Fixer for POS Typos
            sales_df_clean['Name'] = sales_df_clean['Name'].replace({'JAL JAWAN RUM': 'JAI JAWAN RUM'})
            stock_df_clean['Name'] = stock_df_clean['Name'].replace({'JAL JAWAN RUM': 'JAI JAWAN RUM'})

            if stock_df_clean.empty or sales_df_clean.empty:
                st.error("Could not find valid data. Please ensure your files have a 'Name' and '60' column.")
                st.stop()
            
            merged = pd.merge(sales_df_clean, stock_df_clean, on='Name', suffixes=('_sales', '_stock'), how='outer')
            merged['Category'] = merged['Category_stock'].fillna(merged['Category_sales'])
            
            math_cols = ['750_sales', '500_sales', '375_sales', '180_sales', '1l_sales', '60_sales',
                         '750_stock', '500_stock', '375_stock', '180_stock', '1l_stock', '60_stock']
            for col in math_cols:
                if col in merged.columns:
                    merged[col] = merged[col].fillna(0)
            
            pattern_1L = '|'.join(bottles_1L) if bottles_1L else '___DO_NOT_MATCH___'
            pattern_700 = '|'.join(bottles_700ml) if bottles_700ml else '___DO_NOT_MATCH___'
            
            conditions = [
                (merged['Category'] == 'BEER'),
                (merged['Name'].str.contains(pattern_1L, case=False, na=False)), 
                (merged['1l_stock'] > 0) | (merged['1l_sales'] > 0),           
                (merged['Name'].str.contains(pattern_700, case=False, na=False)) 
            ]
            choices = [1.0, 16.67, 16.67, 11.67]
            merged['divisor'] = np.select(conditions, choices, default=12.5)
            
            is_1L_pouring = (merged['divisor'] == 16.67)
            
            merged['1L_Sales_Total'] = np.where(is_1L_pouring, merged['1l_sales'] + (merged['60_sales'] / merged['divisor']), merged['1l_sales'])
            merged['1L_Stock_Total'] = np.where(is_1L_pouring, merged['1l_stock'] + (merged['60_stock'] / merged['divisor']), merged['1l_stock'])
            merged['Difference_1L'] = merged['1L_Sales_Total'] - merged['1L_Stock_Total']
            
            merged['750_Sales_Total'] = np.where(is_1L_pouring, merged['750_sales'], merged['750_sales'] + (merged['60_sales'] / merged['divisor']))
            merged['750_Stock_Total'] = np.where(is_1L_pouring, merged['750_stock'], merged['750_stock'] + (merged['60_stock'] / merged['divisor']))
            merged['Difference_750'] = merged['750_Sales_Total'] - merged['750_Stock_Total']
            
            merged['Difference_500'] = merged['500_sales'] - merged['500_stock']
            merged['Difference_375'] = merged['375_sales'] - merged['375_stock']
            merged['Difference_180'] = merged['180_sales'] - merged['180_stock']
            
            merged['1L_Required'] = merged['Difference_1L'].apply(custom_round)
            merged['750_Required'] = merged['Difference_750'].apply(custom_round)
            merged['500_Required'] = merged['Difference_500'].apply(custom_round)
            merged['375_Required'] = merged['Difference_375'].apply(custom_round)
            merged['180_Required'] = merged['Difference_180'].apply(custom_round)
            
            merged['Math Audit'] = (
                "Sales: " + merged['750_sales'].astype(str) + "(750) + " + merged['1l_sales'].astype(str) + "(1L) + " + merged['60_sales'].astype(str) + "(60) || " +
                "Stock: " + merged['750_stock'].astype(str) + "(750) + " + merged['1l_stock'].astype(str) + "(1L) + " + merged['60_stock'].astype(str) + "(60)"
            )
            
            merged['Original_Order'] = merged['Original_Order'].fillna(999999)
            
            purchase_order = merged[['Name', '1L_Required', '750_Required', '500_Required', '375_Required', '180_Required', 'Math Audit', 'Original_Order']].copy()
            
            final_output = purchase_order.rename(
                columns={
                    '1L_Required': '1-Litre Required',
                    '750_Required': '750ml/700ml Required',
                    '500_Required': '500ml Required',
                    '375_Required': '375ml Required',
                    '180_Required': '180ml Required'
                }
            )
            final_output = final_output.sort_values(by='Original_Order').drop(columns=['Original_Order'])
            
            # --- DISPLAY & DOWNLOAD CSV ---
            st.success("✅ Purchase Order Generated Successfully!")
            st.dataframe(final_output, use_container_width=True)
            
            # Convert dataframe directly to a UTF-8 CSV file
            csv_data = final_output.to_csv(index=False).encode('utf-8')
            
            st.download_button(
                label="📥 Download CSV Purchase Order",
                data=csv_data,
                file_name="Benhur_Liquor_Order.csv",
                mime="text/csv",
                type="primary"
            )
