import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re

# 지도 라이브러리 체크
try:
    from streamlit_folium import st_folium
    import folium
    HAS_MAP_LIBS = True
except ImportError:
    HAS_MAP_LIBS = False

# --- 데이터베이스 및 리소스 설정 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

@st.cache_resource
def initialize_system():
    """DB 추출 및 초기 설정"""
    if not os.path.exists(DB_NAME) and os.path.exists(ZIP_NAME):
        with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
            zip_ref.extractall('./')
    return True

def run_query(query):
    """안전한 데이터 조회를 위한 컨텍스트 매니저 사용"""
    with sqlite3.connect(DB_NAME) as conn:
        return pd.read_sql_query(query, conn)

# 주소 정제 함수
def extract_base_address(address):
    if not address: return ""
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

# --- 페이지 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")
initialize_system()

# 1. 컬럼명 캐싱
@st.cache_data
def get_column_names():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
        return [description[0] for description in cursor.description]

all_cols = get_column_names()

# --- 레이아웃 ---
header_col, config_col = st.columns([3.5, 6.5])
with header_col:
    st.title("🚀 환경부 통합 검색")
    st.caption("안정성 최우선 모드 (250MB 최적화)")

with config_col:
    inner_col1, inner_col2, inner_col3 = st.columns([1, 2, 1])
    with inner_col1:
        view_mode = st.radio("보기 방식", ["상세 데이터", "사이트별 통합"])
    with inner_col2:
        default_cols = ['충전소명', '도로명주소', '운영기관명칭', '충전용량', '위치정보']
        selected_display_cols = st.multiselect("표시 컬럼", options=all_cols, default=[c for c in default_cols if c in all_cols])
    with inner_col3:
        map_style = st.selectbox("지도 스타일", ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"])

st.divider()

# --- 검색 인터페이스 ---
s_col1, s_col2 = st.columns([1, 3])
with s_col1:
    search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
with s_col2:
    search_query = st.text_input("검색어 입력 (예: '산들 !에버온')", placeholder="입력 후 엔터를 눌러주세요")

# --- 검색 실행 및 결과 유지 ---
if search_query:
    # 2. 검색 엔진 최적화 (SQL 문 생성)
    keywords = search_query.split()
    include_words = [w for w in keywords if not w.startswith('!')]
    exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

    where_clauses = []
    for word in include_words:
        if search_target == "전체":
            # 성능을 위해 주요 텍스트 컬럼에서만 검색
            where_clauses.append(f"(도로명주소 LIKE '%{word}%' OR 충전소명 LIKE '%{word}%' OR 운영기관명칭 LIKE '%{word}%')")
        else:
            where_clauses.append(f"\"{search_target}\" LIKE '%{word}%'")
    
    for word in exclude_words:
        where_clauses.append(f"NOT (도로명주소 LIKE '%{word}%' OR 충전소명 LIKE '%{word}%' OR 운영기관명칭 LIKE '%{word}%')")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    
    # 3. 데이터 로드 (최대 3000건으로 제한하여 메모리 보호)
    final_sql = f"SELECT * FROM env_data WHERE {where_sql} LIMIT 3000"
    
    @st.cache_data(show_spinner=False)
    def fetch_data(sql):
        df = run_query(sql)
        if not df.empty and '위치정보' in df.columns:
            # 좌표 데이터 미리 숫자화
            coords = df['위치정보'].astype(str).str.split(',', expand=True)
            if coords.shape[1] >= 2:
                df['lat'] = pd.to_numeric(coords[0], errors='coerce')
                df['lon'] = pd.to_numeric(coords[1], errors='coerce')
        return df

    try:
        df_result = fetch_data(final_sql)

        if not df_result.empty:
            df_result['충전기대수'] = 1
            
            # 사이트 통합 가공
            if view_mode == "사이트별 통합":
                df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                # 그룹화 대상 컬럼 필터링
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

            # 지표 표시
            m1, m2 = st.columns(2)
            m1.metric("표시된 결과 수", f"{len(df_result):,} 건")
            m2.metric("통합 사이트 수", f"{len(display_df):,} 개")

            tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])
            
            with tab1:
                st.dataframe(display_df, use_container_width=True)

            with tab2:
                if HAS_MAP_LIBS:
                    # 지도는 최대 1000개만 표시하여 브라우저 다운 방지
                    map_ready = display_df.dropna(subset=['lat', 'lon']).head(1000)
                    if not map_ready.empty:
                        if len(display_df) > 1000:
                            st.info("💡 결과가 너무 많아 상위 1,000개 사이트만 지도에 표시합니다.")
                        
                        m = folium.Map(location=[map_ready['lat'].mean(), map_ready['lon'].mean()], zoom_start=12, tiles=map_style)
                        for _, row in map_ready.iterrows():
                            color = 'blue' if '에버온' in str(row['운영기관명칭']) else 'red'
                            folium.CircleMarker(
                                location=[row['lat'], row['lon']],
                                radius=6, color=color, fill=True, fill_opacity=0.6,
                                popup=f"<b>{row.get('사이트명', '충전소')}</b><br>{row.get('운영기관명칭','-')}<br>{row.get('충전기대수', 1)}대"
                            ).add_to(m)
                        st_folium(m, width=None, height=600, use_container_width=True, key="stable_map")
                    else:
                        st.warning("위치 정보가 없습니다.")
                else:
                    st.error("지도 라이브러리 설치 필요")
        else:
            st.warning("결과가 없습니다. 검색어를 바꿔보세요.")
    except Exception as inner_e:
        st.error(f"데이터 처리 중 오류: {inner_e}")

else:
    st.info("상단에 검색어를 입력하고 엔터를 누르면 분석이 시작됩니다.")

st.divider()
st.caption("© 2026 고속 검색 엔진 - 안정화 버전 적용됨")
