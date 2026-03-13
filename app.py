import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re

# --- 파일 및 DB 설정 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

def prepare_db():
    if not os.path.exists(DB_NAME):
        if os.path.exists(ZIP_NAME):
            with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
                zip_ref.extractall('./')
        else:
            st.error("데이터 파일(data.db 또는 data.db.zip)을 찾을 수 없습니다.")
            st.stop()

def run_query(query):
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()
    return df

def extract_base_address(address):
    if not address: return ""
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

# [중요] '위치정보' 컬럼(위도,경도)에서 좌표를 추출하는 함수
def parse_lat_lon(df):
    if '위치정보' in df.columns:
        # 쉼표를 기준으로 앞은 위도(lat), 뒤는 경도(lon)로 분리
        coords = df['위치정보'].str.split(',', expand=True)
        if coords.shape[1] >= 2:
            df['lat'] = pd.to_numeric(coords[0], errors='coerce')
            df['lon'] = pd.to_numeric(coords[1], errors='coerce')
    return df

# --- 페이지 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")
prepare_db()

@st.cache_data
def get_column_names():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
    cols = [description[0] for description in cursor.description]
    conn.close()
    return cols

try:
    all_cols = get_column_names()
    
    # --- 상단 레이아웃 (3.5:6.5) ---
    header_col, config_col = st.columns([3.5, 6.5])

    with header_col:
        st.title("🚀 환경부 통합 검색 & 지도")
        st.markdown("위치정보 좌표를 기반으로 분포를 확인합니다.")

    with config_col:
        st.markdown("##### ⚙️ 보기 방식 및 표시 컬럼 설정")
        inner_col1, inner_col2 = st.columns([1, 2.5])
        with inner_col1:
            view_mode = st.radio("보기 방식", ["상세 데이터", "사이트별 통합"], horizontal=False)
        with inner_col2:
            # 기본 컬럼에 '위치정보' 포함
            default_cols = [
                '충전소명', '도로명주소', '운영기관명칭', '충전용량', '설치년도', '위치정보'
            ]
            actual_default = [c for c in default_cols if c in all_cols]
            selected_display_cols = st.multiselect("표시할 컬럼을 선택하세요", options=all_cols, default=actual_default)

    st.divider()
    
    # --- 검색 영역 ---
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력", placeholder="아파트 이름이나 주소를 입력하세요")

    if search_query:
        with st.spinner('위치 데이터 분석 중...'):
            # 1차 주소 검색 및 유관 데이터 확장
            if search_target == "전체":
                where_clauses = [f"\"{col}\" LIKE '%{search_query}%'" for col in all_cols]
                sql_primary = f"SELECT 도로명주소 FROM env_data WHERE {' OR '.join(where_clauses)} LIMIT 1000"
            else:
                sql_primary = f"SELECT 도로명주소 FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 1000"
            
            primary_addresses = run_query(sql_
