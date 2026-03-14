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

# --- 설정 및 DB 준비 ---
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
    """SQL 쿼리를 실행하여 데이터프레임으로 반환 (메모리 효율적)"""
    with sqlite3.connect(DB_NAME, check_same_thread=False) as conn:
        return pd.read_sql_query(query, conn)

def extract_base_address(address):
    if not address: return ""
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

# --- 앱 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")
prepare_db()

# 컬럼 목록 가져오기 (데이터 로드 전 가볍게 확인)
@st.cache_data
def get_column_names():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
        return [description[0] for description in cursor.description]

try:
    all_cols = get_column_names()
    
    # 상단 레이아웃 (3.5:6.5)
    header_col, config_col = st.columns([3.5, 6.5])
    with header_col:
        st.title("🚀 환경부 통합 검색")
        st.caption("안정성이 강화된 고속 검색 엔진")

    with config_col:
        inner_col1, inner_col2, inner_col3 = st.columns([1, 2, 1])
        with inner_col1:
            view_mode = st.radio("보기 방식", ["상세 데이터", "사이트별 통합"])
        with inner_col2:
            default_cols = ['충전소명', '도로명주소', '운영기관명칭', '충전용량', '설치년도', '위치정보']
            selected_display_cols = st.multiselect("표시 컬럼", options=all_cols, default=[c for c in default_cols if c in all_cols])
        with inner_col3:
            map_style = st.selectbox("지도 스타일", ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"])

    st.divider()

    # 검색바
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력 (예: '산들 !에버온')", key="search_input")

    if search_query:
        # 1. SQL 쿼리 생성 (단어별 필터링)
        keywords = search_query.split()
        include_words = [w for w in keywords if not w.startswith('!')]
        exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

        # 기본 WHERE 절 생성
        where_clauses = []
        for word in include_words:
            if search_target == "전체":
                # 전체 검색 시 주요 컬럼만 검색하여 성능 향상
                where_clauses.append(f"(도로명주소 LIKE '%{word}%' OR 충전소명 LIKE '%{word}%' OR 운영기관명칭 LIKE '%{word}%')")
            else:
                where_clauses.append(f"\"{search_target}\" LIKE '%{word}%'")
        
        for word in exclude_words:
            where_clauses.append(f"NOT (도로명주소 LIKE '%{word}%' OR 충전소명 LIKE '%{word}%' OR 운영기관명칭 LIKE '%{word}%')")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        final_sql = f"SELECT * FROM env_data WHERE {where_sql} LIMIT 3000"

        # 2. 검색 실행
        df_result = run_query(final_sql)

        if not df_result.empty:
            # 좌표 파싱
            if '위치정보' in df_result.columns:
                coords = df_result['위치정보'].astype(str).str.split(',', expand=True)
                if coords.shape[1] >= 2:
                    df_result['lat'] = pd.to_numeric(coords[0], errors='coerce')
                    df_result['lon'] = pd.to_numeric(coords[1], errors='coerce')

            df_result['충전기대수'] = 1
            
            # 사이트 통합 처리
            if view_mode == "사이트별 통합":
                df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                group_keys = ['통합주소', '운영기관명칭']
                agg_rules = {col: 'first' for col in selected_display_cols if col not in group_keys}
                agg_rules['충전기대수'] = 'count'
                if 'lat' in df_result.columns: agg_rules['lat'] = 'first'
                if 'lon' in df_result.columns: agg_rules['lon'] = 'first'
                if '충전소명' in df_result.columns: agg_rules['사이트명'] = 'first'
                
                df_result['사이트명'] = df_result['충전소명']
                display_df = df_result.groupby(group_keys).agg(agg_rules).reset_index()
            else:
                display_df = df_result
                display_df['사이트명'] = display_df.get('충전소명', '정보없음')

            # 결과 지표
            m1, m2 = st.columns(2)
            m1.metric("검색 결과 수 (개별)", f"{len(df_result):,} 건")
            m2.metric("사이트 수", f"{len(display_df):,} 개")

            tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])
            
            with tab1:
                st.dataframe(display_df, use_container_width=True)
                st.download_button("결과 CSV 저장", data=display_df.to_csv(index=False).encode('utf-8-sig'), file_name="search_results.csv")

            with tab2:
                if HAS_MAP_LIBS:
                    map_ready = display_df.dropna(subset=['lat', 'lon'])
                    if not map_ready.empty:
                        m = folium.Map(location=[map_ready['lat'].mean(), map_ready['lon'].mean()], zoom_start=12, tiles=map_style)
                        for _, row in map_ready.iterrows():
                            color = 'blue' if '에버온' in str(row['운영기관명칭']) else 'red'
                            folium.CircleMarker(
                                location=[row['lat'], row['lon']],
                                radius=6, color=color, fill=True, fill_opacity=0.6,
                                popup=f"<b>{row.get('사이트명', '충전소')}</b><br>{row.get('운영기관명칭','-')}<br>{row.get('충전기대수', 1)}대"
                            ).add_to(m)
                        st_folium(m, width=None, height=600, use_container_width=True, key="unique_map_key")
                else:
                    st.error("지도 라이브러리 설치 필요")
        else:
            st.warning("결과가 없습니다.")
    else:
        st.info("검색어를 입력하세요.")

except Exception as e:
    st.error(f"실행 중 에러 발생: {e}")
