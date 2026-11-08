# -*- coding: utf-8 -*-
"""
MOMO 購物網 商品價格查詢與視覺化 (Streamlit)
執行方式：streamlit run momo_app.py
"""
import re
import time

import pandas as pd
import plotly.express as px
import streamlit as st
from curl_cffi import requests

API_URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HOME_URL = "https://www.momoshop.com.tw/"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}


# ----------------------------------------------------------------------
# 爬蟲 (CODE01)
# ----------------------------------------------------------------------
def build_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


@st.cache_data(show_spinner=False, ttl=600)
def crawl_momo(keyword: str, pages: int, delay: float = 1.0) -> pd.DataFrame:
    """爬取多頁商品，回傳 DataFrame(品名、價格、頁數、連結)。"""
    session = requests.Session(impersonate="chrome")  # 模擬 Chrome TLS 指紋
    session.get(HOME_URL, headers=HEADERS)  # 先取得 cookie

    rows = []
    for page in range(1, pages + 1):
        resp = session.post(API_URL, headers=HEADERS, json=build_payload(keyword, page))
        if resp.status_code != 200:
            raise RuntimeError(f"第 {page} 頁請求失敗：HTTP {resp.status_code}\n{resp.text[:300]}")

        goods = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
        if not goods:  # 沒有更多資料就提早結束
            break

        for p in goods:
            code = p.get("goodsCode", "")
            rows.append(
                {
                    "品名": p.get("goodsName", ""),
                    "價格": p.get("goodsPrice", ""),
                    "頁數": page,
                    "連結": f"https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code={code}" if code else "",
                }
            )
        time.sleep(delay)  # 避免請求過快

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # 價格清洗：只保留數字
    df["價格"] = df["價格"].astype(str).str.replace(r"[^\d]", "", regex=True)
    df = df[df["價格"] != ""].copy()
    df["價格"] = df["價格"].astype(int)
    df = df.drop_duplicates(subset=["品名", "價格"]).reset_index(drop=True)
    return df


# ----------------------------------------------------------------------
# 資料處理
# ----------------------------------------------------------------------
PRICE_BINS = [0, 500, 1000, 1500, 2000, 3000, 5000, float("inf")]
PRICE_LABELS = ["<500", "500-999", "1000-1499", "1500-1999", "2000-2999", "3000-4999", "5000+"]


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["價格區間"] = pd.cut(df["價格"], bins=PRICE_BINS, labels=PRICE_LABELS, right=False)
    df["價格區間"] = df["價格區間"].astype(str)

    # 品牌：取品名中【】內的文字，沒有則歸為「其他」
    def get_brand(name: str) -> str:
        m = re.search(r"【(.+?)】", name)
        return m.group(1) if m else "其他"

    df["品牌"] = df["品名"].apply(get_brand)
    top_brands = df["品牌"].value_counts().head(10).index
    df["品牌"] = df["品牌"].where(df["品牌"].isin(top_brands), "其他")
    return df


# ----------------------------------------------------------------------
# 圖表 (CODE02，改用 Plotly：瀏覽器直接渲染中文，不需下載/安裝字型)
# ----------------------------------------------------------------------
def pie_chart(df: pd.DataFrame):
    count = df["價格區間"].value_counts().reindex(PRICE_LABELS).dropna().reset_index()
    count.columns = ["價格區間", "商品數"]
    return px.pie(count, names="價格區間", values="商品數", title="各價格區間商品占比", hole=0.3)


def line_chart(df: pd.DataFrame, sort_by_price: bool):
    d = df.sort_values("價格").reset_index(drop=True) if sort_by_price else df.reset_index(drop=True)
    d["編號"] = d.index + 1
    fig = px.line(
        d, x="編號", y="價格", markers=True, hover_name="品名",
        title="商品價格走勢" + ("（由低到高）" if sort_by_price else "（依搜尋順序）"),
    )
    fig.add_hline(
        y=df["價格"].mean(), line_dash="dash", line_color="red",
        annotation_text=f"平均 {df['價格'].mean():,.0f}",
    )
    fig.update_layout(xaxis_title="商品編號", yaxis_title="價格 (NT$)")
    return fig


def sunburst_chart(df: pd.DataFrame):
    g = df.groupby(["價格區間", "品牌"]).size().reset_index(name="商品數")
    return px.sunburst(g, path=["價格區間", "品牌"], values="商品數", title="價格區間 → 品牌 旭日圖")


# ----------------------------------------------------------------------
# Streamlit 介面
# ----------------------------------------------------------------------
st.set_page_config(page_title="MOMO 價格查詢", page_icon="🛒", layout="wide")
st.title("🛒 MOMO 購物網商品價格查詢與視覺化")

with st.sidebar:
    st.header("查詢條件")
    keyword = st.text_input("商品關鍵字", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=2, step=1)
    delay = st.slider("每頁間隔秒數", 0.5, 5.0, 1.0, 0.5, help="間隔太短可能被網站阻擋")
    chart_type = st.radio("圖表類型", ["圓餅圖", "折線圖", "旭日圖"])
    sort_by_price = False
    if chart_type == "折線圖":
        sort_by_price = st.checkbox("依價格由低到高排序", value=False)
    run = st.button("🔍 查詢", type="primary", use_container_width=True)

if run:
    if not keyword.strip():
        st.warning("請輸入商品關鍵字")
        st.stop()
    try:
        with st.spinner(f"正在爬取「{keyword}」前 {pages} 頁..."):
            data = crawl_momo(keyword.strip(), int(pages), float(delay))
        st.session_state["data"] = data
        st.session_state["keyword"] = keyword.strip()
    except Exception as e:
        st.error(f"爬取失敗：{e}")
        st.stop()

data = st.session_state.get("data")
if data is None:
    st.info("請在左側輸入商品與頁數，然後按「查詢」。")
elif data.empty:
    st.warning("查無資料，請換個關鍵字或稍後再試。")
else:
    df = add_features(data)
    st.subheader(f"「{st.session_state['keyword']}」查詢結果，共 {len(df)} 筆")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("平均價格", f"{df['價格'].mean():,.0f}")
    c2.metric("中位數", f"{df['價格'].median():,.0f}")
    c3.metric("最高價", f"{df['價格'].max():,}")
    c4.metric("最低價", f"{df['價格'].min():,}")

    if chart_type == "圓餅圖":
        fig = pie_chart(df)
    elif chart_type == "折線圖":
        fig = line_chart(df, sort_by_price)
    else:
        fig = sunburst_chart(df)
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        df[["品名", "價格", "品牌", "價格區間", "頁數", "連結"]],
        use_container_width=True,
        column_config={"連結": st.column_config.LinkColumn("連結", display_text="開啟")},
    )

    st.download_button(
        "⬇️ 下載 CSV",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"MOMO_{st.session_state['keyword']}_{time.strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
