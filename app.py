import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re
import pydeck as pdk  # Streamlit 설치 시 기본 포함됨

# --- DB 및 리소스 설정 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

@st.cache_resource
def prepare_system():
    if not os.path.exists(DB_NAME) and os.path.exists(ZIP_NAME):
        with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
            zip_ref.extractall('./')
    return True

def run_query(query):
    with sqlite3.connect(DB_NAME) as conn:
        return pd.read_sql_query(query, conn)

def extract_base_address(address):
    if not address: return ""
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

# --- 앱 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")
prepare_system()

if 'df_result' not in st.session_state:
    st.session_state.df_result = None

# 컬럼 목록 캐싱
@st.cache_data
def get_column_names():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
        return [description[0] for description in cursor.description]

all_cols = get_column_names()

# --- 상단 레이아웃 ---
header_col, config_col = st.columns([3.5, 6.5])
with header_col:
    st.title("🚀 환경부 통합 검색")
    st.caption("설치 없이 작동하는 고성능 지도 모드")

with config_col:
    st.markdown("##### ⚙️ 설정")
    c1, c2 = st.columns(2)
    view_mode = c1.radio("보기 방식", ["상세 데이터", "사이트별 통합"], horizontal=True)
    default_cols = ['충전소명', '도로명주소', '운영기관명칭', '충전용량', '설치년도', '위치정보']
    selected_display_cols = c2.multiselect("표시 컬럼", options=all_cols, default=[c for c in default_cols if c in all_cols])

st.divider()

# --- 검색 영역 (버튼 클릭 방식) ---
with st.form("search_form"):
    s_col1, s_col2, s_col3 = st.columns([1, 3, 0.5])
    search_target = s_col1.selectbox("검색 항목", ["전체"] + all_cols)
    search_query = s_col2.text_input("검색어 입력 (예: '산들 !에버온')", placeholder="단어 순서 무관 검색 및 제외어(!) 지원")
    submit_button = s_col3.form_submit_button("🔍 검색")

if submit_button or st.session_state.df_result is not None:
    if submit_button:
        keywords = search_query.split()
        include_words = [w for w in keywords if not w.startswith('!')]
        exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

        where_clauses = []
        for word in include_words:
            if search_target == "전체":
                where_clauses.append(f"(도로명주소 LIKE '%{word}%' OR 충전소명 LIKE '%{word}%' OR 운영기관명칭 LIKE '%{word}%')")
            else:
                where_clauses.append(f"\"{search_target}\" LIKE '%{word}%'")
        
        for word in exclude_words:
            where_clauses.append(f"NOT (도로명주소 LIKE '%{word}%' OR 충전소명 LIKE '%{word}%' OR 운영기관명칭 LIKE '%{word}%')")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        final_sql = f"SELECT * FROM env_data WHERE {where_sql} LIMIT 3000"
        
        df = run_query(final_sql)
        if not df.empty and '위치정보' in df.columns:
            coords = df['위치정보'].astype(str).str.split(',', expand=True)
            if coords.shape[1] >= 2:
                df['lat'] = pd.to_numeric(coords[0], errors='coerce')
                df['lon'] = pd.to_numeric(coords[1], errors='coerce')
        st.session_state.df_result = df

    df_res = st.session_state.df_result
    if df_res is not None and not df_res.empty:
        df_res['충전기대수'] = 1
        
        if view_mode == "사이트별 통합":
            df_res['통합주소'] = df_res['도로명주소'].apply(extract_base_address)
            group_keys = ['통합주소', '운영기관명칭']
            agg_rules = {col: 'first' for col in selected_display_cols if col not in group_keys}
            agg_rules['충전기대수'] = 'count'
            if 'lat' in df_res.columns: agg_rules['lat'] = 'first'
            if 'lon' in df_res.columns: agg_rules['lon'] = 'first'
            df_res['사이트명'] = df_res['충전소명']
            display_df = df_res.groupby(group_keys).agg(agg_rules).reset_index()
        else:
            display_df = df_res.copy()
            display_df['사이트명'] = display_df.get('충전소명', '정보없음')

        # 상단 지표
        m1, m2 = st.columns(2)
        m1.metric("검색 결과 수", f"{len(df_res):,} 건")
        m2.metric("통합 사이트 수", f"{len(display_df):,} 개")

        tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])
        
        with tab1:
            st.dataframe(display_df, use_container_width=True)

        with tab2:
            map_data = display_df.dropna(subset=['lat', 'lon']).copy()
            if not map_data.empty:
                # 에버온 여부에 따른 색상 컬럼 추가 (RGB 값 [R, G, B, 투명도])
                map_data['color'] = map_data['운영기관명칭'].apply(
                    lambda x: [0, 0, 255, 160] if '에버온' in str(x) else [255, 0, 0, 160]
                )
                
                # Pydeck 지도 설정
                view_state = pdk.ViewState(
                    latitude=map_data['lat'].mean(),
                    longitude=map_data['lon'].mean(),
                    zoom=11,
                    pitch=0
                )
                
                layer = pdk.Layer(
                    "ScatterplotLayer",
                    map_data,
                    get_position='[lon, lat]',
                    get_color='color',
                    get_radius=100,  # 미터 단위 반지름
                    pickable=True
                )
                
                st.pydeck_chart(pdk.Deck(
                    layers=[layer],
                    initial_view_state=view_state,
                    tooltip={"text": "{사이트명}\n운영: {운영기관명칭}\n충전기: {충전기대수}대"}
                ))
            else:
                st.warning("위치 정보가 없습니다.")
    else:
        st.warning("결과가 없습니다.")
