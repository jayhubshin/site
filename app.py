import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os

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

# --- 페이지 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")

st.title("🚀 환경부 데이터 통합 검색기")
st.markdown("환경부 데이터를 실시간으로 조회합니다.")

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
    
    # --- UI 레이아웃 ---
    st.divider()
    
    st.subheader("⚙️ 화면 설정")
    view_mode = st.radio("보기 방식 선택", ["상세 데이터 (충전기별)", "통합 데이터 (사이트별)"], horizontal=True)
    
    # 기본 표시 컬럼 설정 (요청하신 리스트)
    default_cols = ['충전소명', '도로명주소', '상세위치', '충전소구분상세', '운영기관명', '충전용량', '충전기등록일시', '설치년', '설치월']
    actual_default = [c for c in default_cols if c in all_cols]
    
    selected_display_cols = st.multiselect(
        "표시할 컬럼을 선택하세요", 
        options=all_cols, 
        default=actual_default
    )
    
    st.divider()
    
    # --- 검색 설정 ---
    col1, col2 = st.columns([1, 2])
    with col1:
        search_target = st.selectbox("검색할 항목(컬럼) 선택", ["전체"] + all_cols)
    with col2:
        search_query = st.text_input("검색어 입력", placeholder="아파트 이름이나 주소를 입력하세요 (예: 청암1단지)")

    if search_query:
        with st.spinner('데이터 분석 및 사이트 통합 중...'):
            # 검색 쿼리 실행 (검색 효율을 위해 LIMIT 설정)
            if search_target == "전체":
                where_clauses = [f"\"{col}\" LIKE '%{search_query}%'" for col in all_cols]
                sql = f"SELECT * FROM env_data WHERE {' OR '.join(where_clauses)} LIMIT 3000"
            else:
                sql = f"SELECT * FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 3000"
            
            df_result = run_query(sql)

            if view_mode == "통합 데이터 (사이트별)":
                # 1. '도로명주소'를 기준으로 그룹화하여 [사이트명] 결정
                # 동일 주소 내에서 가장 첫 번째 나타나는 충전소명을 대표 사이트명으로 지정
                if '도로명주소' in df_result.columns and '충전소명' in df_result.columns:
                    # 그룹별 대표 사이트명 생성
                    site_map = df_result.groupby('도로명주소')['충전소명'].first().to_dict()
                    df_result['사이트명'] = df_result['도로명주소'].map(site_map)
                    
                    # 2. 숫자형 데이터 전처리
                    if '충전용량' in df_result.columns:
                        df_result['충전용량'] = pd.to_numeric(df_result['충전용량'], errors='coerce').fillna(0)
                    
                    # 3. 그룹화 (사이트명과 도로명주소 기준)
                    group_key = ['도로명주소', '사이트명']
                    
                    # 집계 정의
                    agg_rules = {col: 'first' for col in selected_display_cols if col not in group_key}
                    agg_rules['충전기대수'] = 'count'
                    if '충전용량' in df_result.columns:
                        agg_rules['총충전용량(합계)'] = 'sum'
                    
                    # 임시 카운트 컬럼
                    df_result['충전기대수'] = 1
                    
                    final_df = df_result.groupby(group_key).agg(agg_rules).reset_index()
                    
                    # 컬럼 순서 조정: 사이트명을 맨 앞으로
                    cols_to_show = ['사이트명', '충전기대수'] + [c for c in selected_display_cols if c != '사이트명']
                    if '총충전용량(합계)' in agg_rules:
                        cols_to_show.insert(2, '총충전용량(합계)')
                    
                    st.subheader(f"🔍 통합 검색 결과: {len(final_df):,}개
