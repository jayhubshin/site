import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re
import pydeck as pdk

# --- 1. 파일 및 DB 설정 ---
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
    with sqlite3.connect(DB_NAME, check_same_thread=False) as conn:
        return pd.read_sql_query(query, conn)

def extract_base_address(address):
    if not address: return ""
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

def parse_lat_lon(df):
    if '위치정보' in df.columns:
        coords = df['위치정보'].astype(str).str.replace(' ', '').str.split(',', expand=True)
        if coords.shape[1] >= 2:
            df['lat'] = pd.to_numeric(coords[0], errors='coerce')
            df['lon'] = pd.to_numeric(coords[1], errors='coerce')
            df = df.dropna(subset=['lat', 'lon'])
            df = df[(df['lat'] > 32) & (df['lat'] < 40) & (df['lon'] > 124) & (df['lon'] < 132)]
    return df

# --- 2. 앱 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")
prepare_db()

@st.cache_data
def get_column_names():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
        return [description[0] for description in cursor.description]

try:
    all_cols = get_column_names()
    st.title("🚀 환경부 통합 검색 & 지도")
    
    # --- 3. 검색 영역 ---
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력 (예: '산들 !에버온')", placeholder="검색어를 입력하고 엔터를 누르세요.")

    if search_query:
        with st.spinner('전체 데이터 조회 중...'):
            keywords = search_query.split()
            include_words = [w for w in keywords if not w.startswith('!')]
            exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

            # SQL 검색 (검색 제한 LIMIT 삭제)
            base_word = include_words[0] if include_words else ""
            sql = f"SELECT * FROM env_data WHERE (도로명주소 LIKE '%{base_word}%' OR 충전소명 LIKE '%{base_word}%' OR 운영기관명칭 LIKE '%{base_word}%')"
            df_raw = run_query(sql)

            # 상세 필터링
            def advanced_filter(row):
                row_str = " ".join(row.astype(str).values)
                return all(w in row_str for w in include_words) and not any(w in row_str for w in exclude_words)

            df_result = df_raw[df_raw.apply(advanced_filter, axis=1)].copy()

            if not df_result.empty:
                # 데이터 가공 및 사이트 통합 (기본 보기 방식)
                df_result['충전기대수'] = 1
                df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                
                group_keys = ['통합주소', '운영기관명칭']
                site_map = df_result.groupby(group_keys)['충전소명'].first().reset_index()
                site_map.rename(columns={'충전소명': '사이트명'}, inplace=True)
                df_result = pd.merge(df_result, site_map, on=group_keys, how='left')

                # 사이트별 통합 데이터 생성
                agg_dict = {col: 'first' for col in df_result.columns if col not in group_keys + ['사이트명', '충전기대수']}
                agg_dict['충전기대수'] = 'count'
                target_df = df_result.groupby(group_keys + ['사이트명']).agg(agg_dict).reset_index()

                # --- 4. 검색 결과 요약 표시 ---
                total_sites = len(target_df)
                total_chargers = target_df['충전기대수'].sum()
                
                m1, m2 = st.columns(2)
                m1.metric("🏠 검색된 총 사이트 수", f"{total_sites:,} 개")
                m2.metric("🔌 검색된 총 충전기 수", f"{total_chargers:,} 대")

                # --- 5. 결과 탭 ---
                tab1, tab2 = st.tabs(["📊 검색결과 목록", "📍 지도 분포"])

                with tab1:
                    # 결과 목록에서 직접 컬럼 수정 가능하게 배치
                    requested_cols = ['사이트명', '충전기대수', '충전소명', '도로명주소', '운영기관명칭', '충전용량', '운영개시일', '설치년도']
                    display_options = ['사이트명', '충전기대수'] + [c for c in all_cols if c not in ['사이트명', '충전기대수']]
                    actual_default = [c for c in requested_cols if c in display_options]
                    
                    selected_cols = st.multiselect("📋 표시할 컬럼을 선택/수정하세요:", options=display_options, default=actual_default)

                    # 행 색상 스타일 함수
                    def style_rows(row):
                        color = '#E3F2FD' if '에버온' in str(row['운영기관명칭']) else '#FFEBEE'
                        return [f'background-color: {color}'] * len(row)

                    final
