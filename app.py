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
    """위치정보 형식을 정밀하게 파싱하여 백지 현상 방지"""
    if '위치정보' in df.columns:
        # 공백 제거 및 콤마 기준 분리
        coords = df['위치정보'].astype(str).str.replace(' ', '').str.split(',', expand=True)
        if coords.shape[1] >= 2:
            df['lat'] = pd.to_numeric(coords[0], errors='coerce')
            df['lon'] = pd.to_numeric(coords[1], errors='coerce')
            # 유효하지 않은 좌표(NaN) 제거
            df = df.dropna(subset=['lat', 'lon'])
            # 한국 범위 밖의 잘못된 좌표 필터링 (위도 33~39, 경도 124~132)
            df = df[(df['lat'] > 30) & (df['lat'] < 45) & (df['lon'] > 120) & (df['lon'] < 135)]
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
    
    with st.expander("⚙️ 설정 및 지도 테마", expanded=True):
        c1, c2, c3 = st.columns([1.2, 3, 1.5])
        with c1:
            view_mode = st.radio("보기 방식", ["사이트별 통합", "상세 데이터"])
        with c2:
            requested_cols = ['사이트명', '충전기대수', '충전소명', '도로명주소', '운영기관명칭', '충전용량', '운영개시일', '설치년도']
            actual_default = [c for c in requested_cols if c in all_cols or c in ['사이트명', '충전기대수']]
            selected_display_cols = st.multiselect("표시 컬럼", options=['사이트명', '충전기대수'] + all_cols, default=actual_default)
        with c3:
            # 백지 현상 방지를 위해 검증된 스타일셋 사용
            map_theme_label = st.selectbox("🗺️ 지도 스타일", [
                "Light (기본 주간)", 
                "Road (상세 도로)", 
                "Dark (야간)",
                "Satelite (위성)"
            ])
            theme_dict = {
                "Light (기본 주간)": "light",
                "Road (상세 도로)": "mapbox://styles/mapbox/streets-v11",
                "Dark (야간)": "dark",
                "Satelite (위성)": "satellite"
            }

    st.divider()
    
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력")

    if search_query:
        # (기존 SQL 및 데이터 필터링 로직 동일)
        # ... [중략] ...
        sql_final = f"SELECT * FROM env_data WHERE (도로명주소 LIKE '%{search_query.split()[0]}%' OR 충전소명 LIKE '%{search_query.split()[0]}%') LIMIT 3000"
        df_result = run_query(sql_final)
        # 제외어 및 세부 필터링 적용 (기존 로직 유지)

        if not df_result.empty:
            df_result['충전기대수'] = 1
            df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
            
            # 사이트명/그룹화 로직 적용
            # ... [중략] ...
            target_df = df_result # (실제 코드에서는 그룹화 로직 포함)

            tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])

            with tab1:
                # 스타일링 적용된 데이터프레임 출력
                st.dataframe(target_df[selected_display_cols], use_container_width=True)

            with tab2:
                # 좌표 정제
                map_df = parse_lat_lon(target_df.copy())
                
                if not map_df.empty:
                    # 점 색상 설정
                    map_df['color'] = map_df['운영기관명칭'].apply(
                        lambda x: [0, 102, 204, 200] if '에버온' in str(x) else [204, 0, 0, 200]
                    )
                    
                    # 지도 시점 자동 설정
                    mid_lat = map_df['lat'].median()
                    mid_lon = map_df['lon'].median()
                    
                    st.pydeck_chart(pdk.Deck(
                        map_style=theme_dict[map_theme_label],
                        initial_view_state=pdk.ViewState(
                            latitude=mid_lat,
                            longitude=mid_lon,
                            zoom=10,
                            pitch=0
                        ),
                        layers=[
                            pdk.Layer(
                                "ScatterplotLayer",
                                map_df,
                                get_position='[lon, lat]',
                                get_color='color',
                                get_radius=100,
                                pickable=True,
                                stroked=True,
                                get_line_color=[255, 255, 255]
                            )
                        ],
                        tooltip={"text": "{사이트명}\n{운영기관명칭}"}
                    ))
                else:
                    st.error("좌표 데이터가 올바르지 않아 지도를 표시할 수 없습니다.")
except Exception as e:
    st.error(f"오류: {e}")
