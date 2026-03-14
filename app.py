import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re
import pydeck as pdk

# --- 1. DB 및 리소스 설정 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

@st.cache_resource
def prepare_system():
    """DB 파일 추출 및 초기화"""
    if not os.path.exists(DB_NAME) and os.path.exists(ZIP_NAME):
        with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
            zip_ref.extractall('./')
    return True

def run_query(query):
    """SQL 엔진을 사용하여 필요한 데이터만 로드"""
    with sqlite3.connect(DB_NAME) as conn:
        return pd.read_sql_query(query, conn)

def extract_base_address(address):
    """주소에서 '로/길 + 건물번호'까지만 추출하여 사이트 통합 기준 마련"""
    if not address: return ""
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

# --- 2. 앱 기본 설정 ---
st.set_page_config(page_title="환경부 검색 시스템", layout="wide")
prepare_system()

# 세션 상태 초기화 (검색 결과 유지용)
if 'df_result' not in st.session_state:
    st.session_state.df_result = None

# 컬럼 목록 캐싱
@st.cache_data
def get_column_names():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
        return [description[0] for description in cursor.description]

all_cols = get_column_names()

# --- 3. 상단 레이아웃 ---
st.title("🚀 환경부 통합 검색 시스템")
st.caption("주간 테마 고정 | 개별 마커 표시 | 에버온(파랑) 구분")

# --- 4. 검색 필터 영역 ---
with st.form("search_form"):
    col1, col2, col3, col4 = st.columns([1, 2, 2, 0.5])
    
    with col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with col2:
        search_query = st.text_input("검색어 입력", placeholder="예: '산들 !에버온' (순서무관, !제외)")
    with col3:
        view_mode = st.radio("보기 방식", ["상세 데이터", "사이트별 통합"], horizontal=True)
    with col4:
        st.write("") # 간격 맞춤
        submit_button = st.form_submit_button("🔍 검색")

# --- 5. 데이터 처리 및 로직 ---
if submit_button or st.session_state.df_result is not None:
    if submit_button:
        # 단어 분리 (포함어 / 제외어)
        keywords = search_query.split()
        include_words = [w for w in keywords if not w.startswith('!')]
        exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

        # SQL WHERE 절 동적 생성
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
        
        # 데이터 가져오기 및 좌표 처리
        df = run_query(final_sql)
        if not df.empty and '위치정보' in df.columns:
            coords = df['위치정보'].astype(str).str.split(',', expand=True)
            if coords.shape[1] >= 2:
                df['lat'] = pd.to_numeric(coords[0], errors='coerce')
                df['lon'] = pd.to_numeric(coords[1], errors='coerce')
        st.session_state.df_result = df

    # 결과 데이터 가공
    df_res = st.session_state.df_result
    if df_res is not None and not df_res.empty:
        df_res['충전기대수'] = 1
        
        if view_mode == "사이트별 통합":
            df_res['통합주소'] = df_res['도로명주소'].apply(extract_base_address)
            # 그룹화 (주요 정보 보존)
            display_df = df_res.groupby(['통합주소', '운영기관명칭']).agg({
                '충전소명': 'first', 
                'lat': 'first', 
                'lon': 'first',
                '충전기대수': 'count'
            }).reset_index()
            display_df.rename(columns={'충전소명': '대표사이트명'}, inplace=True)
        else:
            display_df = df_res.copy()
            display_df['대표사이트명'] = display_df.get('충전소명', '정보없음')

        # 상단 요약 지표
        m1, m2 = st.columns(2)
        m1.metric("표시 결과 건수", f"{len(df_res):,} 건")
        m2.metric("검색된 사이트(지점) 수", f"{len(display_df):,} 개")

        # 결과 출력 (탭 구성)
        tab1, tab2 = st.tabs(["📊 데이터 리스트", "📍 주간 테마 지도"])
        
        with tab1:
            st.dataframe(display_df, use_container_width=True)
            st.download_button("결과 CSV 다운로드", data=display_df.to_csv(index=False).encode('utf-8-sig'), file_name="ev_search_result.csv")

        with tab2:
            map_data = display_df.dropna(subset=['lat', 'lon']).copy()
            if not map_data.empty:
                # 색상 설정: 에버온(파랑), 나머지(빨강)
                map_data['color'] = map_data['운영기관명칭'].apply(
                    lambda x: [0, 100, 255, 180] if '에버온' in str(x) else [255, 50, 50, 180]
                )
                
                # 지도 초기 시점 (검색 결과 중심)
                view_state = pdk.ViewState(
                    latitude=map_data['lat'].mean(),
                    longitude=map_data['lon'].mean(),
                    zoom=11,
                    pitch=0
                )
                
                # 마커 레이어 (Scatterplot)
                layer = pdk.Layer(
                    "ScatterplotLayer",
                    map_data,
                    get_position='[lon, lat]',
                    get_color='color',
                    get_radius=120, # 점의 크기 (미터 단위)
                    pickable=True,
                    auto_highlight=True
                )
                
                # 지도 렌더링 (주간 테마 고정)
                st.pydeck_chart(pdk.Deck(
                    map_style="mapbox://styles/mapbox/light-v10", # 주간(Light) 스타일 고정
                    layers=[layer],
                    initial_view_state=view_state,
                    tooltip={
                        "html": "<b>사이트:</b> {대표사이트명}<br/><b>운영사:</b> {운영기관명칭}<br/><b>충전기:</b> {충전기대수}대",
                        "style": {"backgroundColor": "white", "color": "black", "fontSize": "12px"}
                    }
                ))
            else:
                st.warning("지도에 표시할 위치 정보(좌표)가 없습니다.")
    else:
        st.warning("검색 결과가 없습니다. 다른 검색어를 입력해 보세요.")
else:
    st.info("검색어를 입력하고 '검색' 버튼을 눌러주세요.")

st.divider()
st.caption("© 2026 환경부 EV 검색 시스템 | 라이브러리 설치 없이 바로 작동하는 안정화 버전")
