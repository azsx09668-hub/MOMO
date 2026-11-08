import re
import time

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# ----------------------------------------------------------------------
# 頁面設定
# ----------------------------------------------------------------------
st.set_page_config(page_title="MOMO 商品價格查詢", page_icon="🛒", layout="wide")

URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    )
}

PRICE_BINS = [0, 300, 500, 800, 1000, 1500, 2000, 3000, float("inf")]
PRICE_LABELS = [
    "0-300",
    "301-500",
    "501-800",
    "801-1000",
    "1001-1500",
    "1501-2000",
    "2001-3000",
    "3000以上",
]


# ----------------------------------------------------------------------
# 爬蟲 (原 CODE01)
# ----------------------------------------------------------------------
def build_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "specialGoodsType": "",
            "isBrandSeriesPage": "false",
            "authorNo": "",
            "originalCateCode": "",
            "cateType": "",
            "searchValue": keyword,
            "cateCode": "",
            "cateLevel": "-1",
            "cp": "N",
            "NAM": "N",
            "first": "N",
            "freeze": "N",
            "superstore": "N",
            "tvshop": "N",
            "china": "N",
            "tomorrow": "N",
            "stockYN": "N",
            "prefere": "N",
            "threeHours": "N",
            "video": "N",
            "cycle": "N",
            "cod": "N",
            "superstorePay": "N",
            "showType": "chessboardType",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "searchType": "1",
            "reduceKeyword": "",
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
            "adSource": "tenmax",
        },
    }


def extract_brand(name: str) -> str:
    """從品名擷取品牌：優先抓【】內文字，否則取第一個詞。"""
    m = re.search(r"【([^】]+)】", name)
    if m:
        return m.group(1).strip()
    first = re.split(r"[\s/／]", name.strip())[0]
    return first[:8] if first else "未知"


@st.cache_data(show_spinner=False, ttl=600)
def fetch_products(keyword: str, pages: int) -> pd.DataFrame:
    rows = []
    for page in range(1, pages + 1):
        resp = requests.post(
            URL, headers=HEADERS, json=build_payload(keyword, page), timeout=15
        )
        resp.raise_for_status()
        goods = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
        if not goods:  # 沒有更多資料就提早結束
            break
        for g in goods:
            code = g.get("goodsCode", "")
            rows.append(
                {
                    "頁數": page,
                    "品名": g.get("goodsName", ""),
                    "價格": g.get("goodsPrice", ""),
                    "連結": (
                        f"https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code={code}"
                        if code
                        else ""
                    ),
                }
            )
        time.sleep(0.8)  # 禮貌性延遲，避免被封鎖

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # 價格清洗 (原 CODE01 後半段)
    df["價格"] = df["價格"].astype(str).str.replace(r"[^\d]", "", regex=True)
    df = df[df["價格"] != ""].copy()
    df["價格"] = df["價格"].astype(int)
    df = df.drop_duplicates(subset=["品名", "價格"]).reset_index(drop=True)

    df["品牌"] = df["品名"].apply(extract_brand)
    df["價格區間"] = pd.cut(
        df["價格"], bins=PRICE_BINS, labels=PRICE_LABELS, right=True
    ).astype(str)
    return df


# ----------------------------------------------------------------------
# 圖表 (原 CODE02，改用 Plotly；瀏覽器端渲染，不需另外安裝中文字型)
# ----------------------------------------------------------------------
def top_brand_df(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    tmp = df.copy()
    top = tmp["品牌"].value_counts().head(top_n).index
    tmp["品牌"] = tmp["品牌"].where(tmp["品牌"].isin(top), "其他")
    return tmp


def pie_chart(df: pd.DataFrame):
    cnt = (
        df["價格區間"]
        .value_counts()
        .reindex(PRICE_LABELS)
        .dropna()
        .reset_index()
    )
    cnt.columns = ["價格區間", "數量"]
    fig = px.pie(
        cnt, names="價格區間", values="數量", hole=0.35, title="價格區間分布圓餅圖"
    )
    fig.update_traces(textinfo="label+percent+value")
    return fig


def line_chart(df: pd.DataFrame, limit: int):
    d = df.head(limit)
    mean_price = df["價格"].mean()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=d.index,
            y=d["價格"],
            mode="lines+markers",
            name="價格",
            text=d["品名"],
            hovertemplate="編號 %{x}<br>價格 $%{y:,}<br>%{text}<extra></extra>",
        )
    )
    fig.add_hline(
        y=mean_price,
        line_dash="dash",
        line_color="red",
        annotation_text=f"平均 ${mean_price:,.0f}",
    )
    fig.update_layout(
        title="商品價格折線圖", xaxis_title="商品編號 (store id)", yaxis_title="價格"
    )
    return fig


def sunburst_chart(df: pd.DataFrame, top_n: int):
    d = top_brand_df(df, top_n)
    agg = d.groupby(["價格區間", "品牌"]).size().reset_index(name="數量")
    fig = px.sunburst(
        agg,
        path=["價格區間", "品牌"],
        values="數量",
        title="價格區間 → 品牌 旭日圖",
    )
    fig.update_traces(textinfo="label+value")
    fig.update_layout(height=650)
    return fig


# ----------------------------------------------------------------------
# 介面
# ----------------------------------------------------------------------
st.title("🛒 MOMO 購物網商品價格查詢")
st.caption("輸入商品關鍵字與爬取頁數，即時查詢並視覺化價格分布")

with st.sidebar:
    st.header("查詢條件")
    keyword = st.text_input("商品關鍵字", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=3, step=1)
    chart_type = st.selectbox("圖表類型", ["圓餅圖", "折線圖", "旭日圖"])
    if chart_type == "折線圖":
        line_limit = st.slider("折線圖顯示筆數", 10, 500, 70, step=10)
    if chart_type == "旭日圖":
        top_n = st.slider("旭日圖顯示前幾大品牌", 3, 15, 8)
    run = st.button("🔍 開始查詢", type="primary", use_container_width=True)

if run:
    if not keyword.strip():
        st.warning("請輸入商品關鍵字")
        st.stop()
    try:
        with st.spinner(f"正在爬取「{keyword}」共 {pages} 頁…"):
            st.session_state["df"] = fetch_products(keyword.strip(), int(pages))
            st.session_state["keyword"] = keyword.strip()
    except requests.RequestException as e:
        st.error(f"請求失敗：{e}")
        st.stop()

df = st.session_state.get("df")

if df is None:
    st.info("請在左側輸入條件後按「開始查詢」")
elif df.empty:
    st.warning("查無資料，請換個關鍵字或稍後再試")
else:
    st.subheader(f"「{st.session_state['keyword']}」查詢結果")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("商品數", f"{len(df):,}")
    c2.metric("平均價格", f"${df['價格'].mean():,.0f}")
    c3.metric("最高價格", f"${df['價格'].max():,}")
    c4.metric("最低價格", f"${df['價格'].min():,}")

    if chart_type == "圓餅圖":
        st.plotly_chart(pie_chart(df), use_container_width=True)
    elif chart_type == "折線圖":
        st.plotly_chart(line_chart(df, line_limit), use_container_width=True)
    else:
        st.plotly_chart(sunburst_chart(df, top_n), use_container_width=True)

    st.subheader("商品明細")
    st.dataframe(
        df[["頁數", "品名", "品牌", "價格", "價格區間", "連結"]],
        use_container_width=True,
        column_config={"連結": st.column_config.LinkColumn("連結", display_text="前往")},
    )

    st.download_button(
        "⬇️ 下載 CSV",
        data=df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=f"MOMO_{st.session_state['keyword']}.csv",
        mime="text/csv",
    )
