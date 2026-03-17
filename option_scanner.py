import streamlit as st
import yfinance as ticker_data
import pandas as pd
import numpy as np
from datetime import datetime, date
from scipy.stats import norm
import base64

# --- 版本控制 ---
VERSION = "1.8"

# --- 登录验证 ---
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False
    if "password_correct" not in st.session_state:
        st.text_input("请输入访问密码", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("密码错误，请重新输入", type="password", on_change=password_entered, key="password")
        st.error("😕 访问受限")
        return False
    return True

def calculate_metrics(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return 0, 0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    delta = norm.cdf(d1) - 1
    itm_prob = norm.cdf(-d2)
    return delta, itm_prob

st.set_page_config(page_title=f"期权深度扫描器 V{VERSION}", layout="wide")

if check_password():
    st.title(f"🎯 高质量卖 Put (收租) 深度扫描器 V{VERSION}")
    
    with st.sidebar:
        st.header("🔍 扫描配置")
        market = st.radio("选择市场", ["美股 (US)", "港股 (HK)"])
        tickers_input = st.text_area("股票池", "AAPL,TSLA:150,NVDA,MSFT,GOOG,AMZN")
        
        st.divider()
        min_premium = st.number_input("最小权利金 (单股)", value=5.0)
        min_otm = st.slider("最小虚值深度 (OTM %)", 0, 50, 20) / 100
        max_assign_prob = st.slider("最大行权概率 ≤ (%)", 0, 100, 20) / 100
        delta_range = st.slider("|Delta| 区间", 0.0, 0.5, (0.02, 0.15))
        
        st.divider()
        min_dte = st.number_input("最小剩余天数", value=45)
        max_dte = st.number_input("最大剩余天数", value=365)
        min_vol = st.number_input("最小成交量", value=1)
        max_spread = st.slider("买卖价差阈值 (%)", 0, 100, 30) / 100
        sort_by = st.selectbox("排序字段", ["虚值距离", "权利金", "权利金年化收益", "行权概率"])

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
                
                expirations = tk.options
                if not expirations:
                    st.warning(f"{sym}: 无法获取行情，Yahoo 正在限制云端访问。")
                    continue
                
                for exp in expirations:
                    days = (datetime.strptime(exp, '%Y-%m-%d').date() - date.today()).days
                    if not (min_dte <= days <= max_dte): continue
                    
                    chain = tk.option_chain(exp)
                    puts = chain.puts
                    valid_puts = puts[(puts['strike'] < current_price) & (puts['strike'] <= (limit_price or 999999))]
                    
                    for _, row in valid_puts.iterrows():
                        mid = (row['bid'] + row['ask']) / 2
                        if mid <= 0: continue
                        delta, itm_prob = calculate_metrics(current_price, row['strike'], max(days,1)/365, r, row['impliedVolatility'])
                        
                        if (mid >= min_premium and (current_price - row['strike'])/current_price >= min_otm and 
                            itm_prob <= max_assign_prob and delta_range[0] <= abs(delta) <= delta_range[1] and
                            row['volume'] >= min_vol):
                            
                            all_results.append({
                                "序号": 0, "股票": sym, "当前股价": round(current_price, 2), "行权价": row['strike'], 
                                "权利金": round(mid, 3), "虚值距离": (current_price - row['strike'])/current_price, 
                                "到期日": exp, "剩余天数": days, "行权概率": itm_prob, "Delta(put)": round(delta, 3), 
                                "权利金年化收益": (mid/row['strike'])*(365/max(days,1))
                            })
            except Exception as e:
                st.error(f"{sym} 扫描出错: {str(e)}")
            progress_bar.progress((idx + 1) / len(ticker_configs))
        
        if all_results:
            df = pd.DataFrame(all_results)
            df = df.sort_values(by=sort_by, ascending=False).reset_index(drop=True)
            df['序号'] = df.index + 1
            st.success(f"✅ 找到 {len(df)} 条结果")
            # 格式化显示
            df_display = df.copy()
            df_display["虚值距离"] = df_display["虚值距离"].apply(lambda x: f"{x:.2%}")
            df_display["行权概率"] = df_display["行权概率"].apply(lambda x: f"{x:.2%}")
            df_display["权利金年化收益"] = df_display["权利金年化收益"].apply(lambda x: f"{x:.2%}")
            st.dataframe(df_display, hide_index=True)
        else:
            st.warning("未找到匹配。建议把‘最小权利金’和‘虚值距离’调低后再试。")
