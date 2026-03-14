import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re

# 지도 관련 라이브러리 체크
try:
    from streamlit_folium import st_folium
    import folium
    HAS_MAP_LIBS = True
except ImportError:
    HAS_MAP_LIBS = False

# --- 데이터베이스 설정 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

@st.cache_resource
def prepare_db():
    if not os.path.exists(DB_NAME):
        if os.path.exists(ZIP_NAME):
            with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
                zip_ref.extractall('./')
    return True

def run_query(query):
    """SQL 엔진을 사용하여 필요한 데이터만 메모리로 가져옴"""
    with sqlite3.connect(DB_NAME) as conn:
        return pd.read_sql_query(query, conn)

def extract_base_address(address):
    if not address: return ""
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

# --- 앱 설정 ---
st.set_page_config(page_title="환경부 검색 시스템", layout="wide")
prepare_db()

# 컬럼 목록 (캐싱)
@st.cache_data
def get_column_names():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
        return [description[0] for description in cursor.description]

all_cols = get_column_names()

# --- 레이아웃 (3.5:6.5) ---
header_col, config_col = st.columns([3.5, 6.5])
with header_col:
    st.title("🚀 환경부 통합 검색")
    st.caption("250MB 대용량 데이터 최적화 모드")

with config_col:
    st.markdown("##### ⚙️ 설정")
    inner_col1, inner_col2, inner_col3 = st.columns([1, 2, 1])
    with inner_col1:
        view_mode = st.radio("보기 방식", ["상세 데이터", "사이트별 통합"])
    with inner_col2:
        default_cols = ['충전소명', '도로명주소', '운영기관명칭', '충전용량', '위치정보']
        selected_display_cols = st.multiselect("표시 컬럼", options=all_cols, default=[c for c in default_cols if c in all_cols])
    with inner_col3:
        map_style = st.selectbox("지도 스타일", ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"])

st.divider()

# --- 검색창 ---
s_col1, s_col2 = st.columns([1, 3])
with s_col1:
    search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
with s_col2:
    search_query = st.text_input("검색어 입력 (예: '산들 !에버온')")

# --- 핵심: 검색 결과 캐싱 (세션 상태 이용) ---
if search_query:
    # SQL 쿼리 빌드
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
    
    # 쿼리 실행 (LIMIT를 두어 메모리 폭주 방지)
    final_sql = f"SELECT * FROM env_data WHERE {where_sql} LIMIT 5000"
    
    # 쿼리 결과가 바뀔 때만 연산 수행
    @st.cache_data(ttl=600) # 10분간 검색 결과 캐싱
    def get_search_results(sql):
        df = run_query(sql)
        if not df.empty and '위치정보' in df.columns:
            coords = df['위치정보'].astype(str).str.split(',', expand=True)
            if coords.shape[1] >= 2:
                df['lat'] = pd.to_numeric(coords[0], errors='coerce')
                df['lon'] = pd.to_numeric(coords[1], errors='coerce')
        return df

    df_result = get_search_results(final_sql)

    if not df_result.empty:
        df_result['충전기대수'] = 1
        
        # 보기 방식에 따른 데이터 가공
        if view_mode == "사이트별 통합":
            df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
            group_keys = ['통합주소', '운영기관명칭']
            agg_rules = {col: 'first' for col in selected_display_cols if col not in group_keys}
            agg_rules['충전기대수'] = 'count'
            if 'lat' in df_result.columns: agg_rules['lat'] = 'first'
            if 'lon' in df_result.columns: agg_rules['lon'] = 'first'
            df_result['사이트명'] = df_result['충전소명']
            display_df = df_result.groupby(group_keys).agg(agg_rules).reset_index()
        else:
            display_df = df_result
            display_df['사이트명'] = display_df.get('충전소명', '정보없음')

        # 상단 지표
        m1, m2 = st.columns(2)
        m1.metric("검색 결과 수", f"{len(df_result):,} 건")
        m2.metric("사이트 수", f"{len(display_df):,} 개")

        tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])
        
        with tab1:
            st.dataframe(display_df, use_container_width=True)

        with tab2:
            if HAS_MAP_LIBS:
                map_ready = display_df.dropna(subset=['lat', 'lon'])
                if not map_ready.empty:
                    # 지도 객체 생성 시 세션 상태에 따라 반복 렌더링 방지
                    m = folium.Map(location=[map_ready['lat'].mean(), map_ready['lon'].mean()], zoom_start=12, tiles=map_style)
                    for _, row in map_ready.iterrows():
                        color = 'blue' if '에버온' in str(row['운영기관명칭']) else 'red'
                        folium.CircleMarker(
                            location=[row['lat'], row['lon']],
                            radius=6, color=color, fill=True, fill_opacity=0.6,
                            popup=f"<b>{row.get('사이트명', '충전소')}</b><br>{row.get('운영기관명칭','-')}<br>{row.get('충전기대수', 1)}대"
                        ).add_to(m)
                    st_folium(m, width=None, height=600, use_container_width=True, key="fixed_map")
            else:
                st.error("지도 라이브러리 설치 필요")
    else:
        st.warning("결과가 없습니다.")
else:
    st.info("검색어를 입력하세요.")
