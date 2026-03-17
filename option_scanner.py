import streamlit as st
import yfinance as ticker_data
import pandas as pd
import numpy as np
from datetime import datetime, date
from scipy.stats import norm
import base64

# --- 版本控制 ---
VERSION = "1.6"
FILE_NAME = f"option_scanner_v1_{VERSION.split('.')[-1]}.py"

def calculate_metrics(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return 0, 0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    delta = norm.cdf(d1) - 1
    itm_prob = norm.cdf(-d2)
    return delta, itm_prob

def get_table_download_link(df):
    csv = df.to_csv(index=False).encode('utf-8-sig')
    b64 = base64.b64encode(csv).decode()
    return f'<a href="data:file/csv;base64,{b64}" download="options_scan_v{VERSION}_{date.today()}.csv">📥 下载扫描结果 (CSV)</a>'

st.set_page_config(page_title=f"期权深度扫描器 V{VERSION}", layout="wide")
st.title(f"🎯 高质量卖 Put (收租) 深度扫描器")
st.markdown(f"**当前运行文件:** `{FILE_NAME}` | **版本:** `V{VERSION}`")

with st.sidebar:
    st.header("🔍 扫描配置")
    market = st.radio("选择市场", ["美股 (US)", "港股 (HK)"])
    tickers_input = st.text_area("股票池", "AAPL,TSLA:150,NVDA,MSFT,GOOG,AMZN" if market=="美股 (US)" else "0700.HK,9988.HK,3690.HK")
    
    st.divider()
    min_premium = st.number_input("最小权利金 (单股)", value=5.0)
    min_otm = st.slider("最小虚值深度 (OTM %)", 0, 50, 20) / 100
    max_assign_prob = st.slider("最大行权概率 ≤ (%)", 0, 100, 20) / 100
    delta_range = st.slider("|Delta| 区间", 0.0, 0.5, (0.02, 0.15))
    
    st.divider()
    min_dte = st.number_input("最小剩余天数", value=45)
    max_dte = st.number_input("最大剩余天数", value=365)
    min_vol = st.number_input("最小成交量", value=1)
    min_oi = st.number_input("最小持仓量", value=10)
    max_spread = st.slider("买卖价差阈值 (%)", 0, 100, 30) / 100

    st.divider()
    st.header("📊 排序设置")
    sort_by = st.selectbox("排序字段", ["虚值距离", "权利金", "权利金年化收益", "行权概率", "剩余天数", "Delta(put)"])
    sort_order = st.radio("排序顺序", ["降序 (从大到小)", "升序 (从小到大)"])

if st.button("🚀 开始扫描"):
    raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
    ticker_configs = {item.split(":")[0]: float(item.split(":")[1]) if ":" in item else None for item in raw_tickers}
            
    all_results = []
    r = 0.04 
    
    progress_bar = st.progress(0)
    for idx, (sym, limit_price) in enumerate(ticker_configs.items()):
        try:
            tk = ticker_data.Ticker(sym)
            current_price = tk.fast_info['last_price']
            for exp in tk.options:
                days = (datetime.strptime(exp, '%Y-%m-%d').date() - date.today()).days
                if not (min_dte <= days <= max_dte): continue
                
                chain = tk.option_chain(exp)
                puts = chain.puts
                valid_puts = puts[(puts['strike'] < current_price) & (puts['strike'] <= (limit_price or 999999))]
                
                for _, row in valid_puts.iterrows():
                    mid = (row['bid'] + row['ask']) / 2
                    if mid <= 0: continue
                    delta, itm_prob = calculate_metrics(current_price, row['strike'], days/365, r, row['impliedVolatility'])
                    
                    if (mid >= min_premium and (current_price - row['strike'])/current_price >= min_otm and 
                        itm_prob <= max_assign_prob and delta_range[0] <= abs(delta) <= delta_range[1] and
                        row['volume'] >= min_vol and (row['ask'] - row['bid'])/mid <= max_spread):
                        
                        all_results.append({
                            "股票": sym, "当前股价": round(current_price, 2), "行权价": row['strike'], "权利金": round(mid, 3),
                            "虚值距离": (current_price - row['strike'])/current_price, "到期日": exp, "剩余天数": days,
                            "行权概率": itm_prob, "Delta(put)": round(delta, 3), "权利金年化收益": (mid/row['strike'])*(365/days),
                            "成交量": int(row['volume']), "持仓量": int(row['openInterest']), "隐含波动率(IV)": f"{row['impliedVolatility']:.2%}",
                            "买卖价差(%)": f"{(row['ask'] - row['bid'])/mid:.2%}", "盈亏平衡价": round(row['strike'] - mid, 2),
                            "合约乘数(股/张)": 100 if market == "美股 (US)" else "需查表",
                            "所需现金(每张)": f"{row['strike'] * 100:,.0f}" if market == "美股 (US)" else "根据乘数计算"
                        })
        except: continue
        progress_bar.progress((idx + 1) / len(ticker_configs))
    
    if all_results:
        df = pd.DataFrame(all_results)
        # 执行排序
        df = df.sort_values(by=sort_by, ascending=(sort_order == "升序 (从小到大)"))
        
        # 核心改进：在排序后重置索引，生成从 1 开始的序号列
        df.reset_index(drop=True, inplace=True)
        df.insert(0, '序号', df.index + 1)
        
        # 格式化百分比（仅用于显示）
        display_df = df.copy()
        display_df["虚值距离"] = display_df["虚值距离"].apply(lambda x: f"{x:.2%}")
        display_df["行权概率"] = display_df["行权概率"].apply(lambda x: f"{x:.2%}")
        display_df["权利金年化收益"] = display_df["权利金年化收益"].apply(lambda x: f"{x:.2%}")

        st.success(f"✅ 扫描完成！本次共获得 **{len(df)}** 个结果。")
        st.dataframe(display_df, hide_index=True)
        st.markdown(get_table_download_link(df), unsafe_allow_html=True)
    else:
        st.warning("未找到匹配合约。")
