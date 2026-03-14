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

# --- 리소스 최적화 설정 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

@st.cache_resource
def init_db():
    if not os.path.exists(DB_NAME) and os.path.exists(ZIP_NAME):
        with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
            zip_ref.extractall('./')
    # 성능 향상을 위해 DB 인덱스 생성 시도 (이미 있으면 무시)
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_addr ON env_data(도로명주소);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON env_data(충전소명);")
    return True

# --- 페이지 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")
init_db()

# 세션 상태 초기화 (검색 결과 유지용)
if 'search_results' not in st.session_state:
    st.session_state.search_results = None

# --- 레이아웃 ---
header_col, config_col = st.columns([3, 7])
with header_col:
    st.title("🚀 통합 검색 시스템")
    st.caption("안정화 필터 적용됨")

with config_col:
    st.markdown("##### ⚙️ 설정")
    c1, c2, c3 = st.columns(3)
    view_mode = c1.radio("보기", ["상세 데이터", "사이트별 통합"], horizontal=True)
    map_style = c2.selectbox("지도", ["OpenStreetMap", "CartoDB positron"])
    # 250MB 대응: 검색 성능을 위해 대상 제한
    search_target = c3.selectbox("대상", ["전체", "도로명주소", "충전소명", "운영기관명칭"])

st.divider()

# --- 검색 영역 (버튼 클릭 방식으로 변경하여 부하 방지) ---
with st.form("search_form"):
    s_col1, s_col2 = st.columns([4, 1])
    query_input = s_col1.text_input("검색어 입력 (예: '산들 !에버온')", placeholder="검색어를 입력하세요")
    submit_button = s_col2.form_submit_button("🔍 검색 실행")

if submit_button or st.session_state.search_results is not None:
    if submit_button:
        # 새로운 검색 시 실행
        keywords = query_input.split()
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
        
        # [핵심] LIMIT 2000으로 서버 타임아웃 방지
        final_sql = f"SELECT * FROM env_data WHERE {where_sql} LIMIT 2000"
        
        with sqlite3.connect(DB_NAME) as conn:
            df = pd.read_sql_query(final_sql, conn)
            
        # 좌표 전처리
        if not df.empty and '위치정보' in df.columns:
            coords = df['위치정보'].astype(str).str.split(',', expand=True)
            if coords.shape[1] >= 2:
                df['lat'] = pd.to_numeric(coords[0], errors='coerce')
                df['lon'] = pd.to_numeric(coords[1], errors='coerce')
        
        st.session_state.search_results = df

    # 결과가 있을 경우 표시
    df_res = st.session_state.search_results
    if df_res is not None and not df_res.empty:
        df_res['충전기대수'] = 1
        
        # 사이트 통합 처리
        if view_mode == "사이트별 통합":
            df_res['통합주소'] = df_res['도로명주소'].apply(lambda x: re.search(r'(.+[로|길]\s*\d+)', str(x)).group(1) if re.search(r'(.+[로|길]\s*\d+)', str(x)) else str(x))
            display_df = df_res.groupby(['통합주소', '운영기관명칭']).agg({
                '충전소명': 'first', 'lat': 'first', 'lon': 'first', '충전기대수': 'count'
            }).reset_index()
            display_df.rename(columns={'충전소명': '사이트명'}, inplace=True)
        else:
            display_df = df_res.copy()
            display_df['사이트명'] = display_df.get('충전소명', '정보없음')

        st.success(f"검색 완료: 총 {len(df_res):,}건 발견")
        
        tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])
        with tab1:
            st.dataframe(display_df, use_container_width=True)
        with tab2:
            if HAS_MAP_LIBS:
                # 지도 부하 방지: 최대 800개 제한
                map_data = display_df.dropna(subset=['lat', 'lon']).head(800)
                if not map_data.empty:
                    m = folium.Map(location=[map_data['lat'].mean(), map_data['lon'].mean()], zoom_start=11, tiles=map_style)
                    for _, row in map_data.iterrows():
                        color = 'blue' if '에버온' in str(row['운영기관명칭']) else 'red'
                        folium.CircleMarker(
                            location=[row['lat'], row['lon']], radius=5, color=color, fill=True, fill_opacity=0.6,
                            popup=f"{row['사이트명']} ({row['운영기관명칭']})"
                        ).add_to(m)
                    # use_container_width 대신 고정 크기(height)를 사용하여 안정성 확보
                    st_folium(m, height=500, width=1000, key="map_stable")
                else:
                    st.warning("위치 정보가 없습니다.")
    else:
        st.warning("결과가 없습니다.")
