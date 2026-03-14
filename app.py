import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re
import pydeck as pdk

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
st.title("🚀 환경부 통합 검색 (주간 테마 고정)")

# --- 검색 영역 ---
with st.form("search_form"):
    s_col1, s_col2, s_col3 = st.columns([1, 3, 0.5])
    search_target = s_col1.selectbox("검색 항목", ["전체"] + all_cols)
    search_query = s_col2.text_input("검색어 입력 (예: '산들 !에버온')", placeholder="단어 순서 무관 검색 및 제외어(!) 지원")
    submit_button = s_col3.form_submit_button("🔍 검색")

if submit_button or st.session_state.df_result is not None:
    if submit_button:
        # 검색 로직 (순서 무관 + 제외어)
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
        # 사이트 통합 처리 (기본값)
        df_res['통합주소'] = df_res['도로명주소'].apply(extract_base_address)
        display_df = df_res.groupby(['통합주소', '운영기관명칭']).agg({
            '충전소명': 'first', 'lat': 'first', 'lon': 'first'
        }).reset_index()
        display_df['충전기대수'] = df_res.groupby(['통합주소', '운영기관명칭'])['충전소명'].transform('count') # 개수 계산 보정

        tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])
        
        with tab1:
