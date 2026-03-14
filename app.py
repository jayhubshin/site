import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re

# 지도 관련 라이브러리
try:
    from streamlit_folium import st_folium
    import folium
    HAS_MAP_LIBS = True
except ImportError:
    HAS_MAP_LIBS = False

# --- 설정 및 데이터 로드 최적화 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

@st.cache_resource
def prepare_db():
    if not os.path.exists(DB_NAME):
        if os.path.exists(ZIP_NAME):
            with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
                zip_ref.extractall('./')
    return True

@st.cache_data
def get_all_data():
    """전체 데이터를 한 번만 로드하여 메모리에 캐싱합니다."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    df = pd.read_sql_query("SELECT * FROM env_data", conn)
    conn.close()
    # 좌표 파싱을 로드 시점에 미리 해두면 검색이 더 빨라집니다.
    if '위치정보' in df.columns:
        coords = df['위치정보'].astype(str).str.split(',', expand=True)
        if coords.shape[1] >= 2:
            df['lat'] = pd.to_numeric(coords[0], errors='coerce')
            df['lon'] = pd.to_numeric(coords[1], errors='coerce')
    return df

# --- 앱 실행 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")
prepare_db()

# 데이터 로드 (캐싱됨)
try:
    full_df = get_all_data()
    all_cols = full_df.columns.tolist()

    # 상단 레이아웃
    header_col, config_col = st.columns([3.5, 6.5])
    with header_col:
        st.title("🚀 환경부 통합 검색 & 지도")
        st.caption("한 번 검색하면 결과가 유지됩니다.")

    with config_col:
        st.markdown("##### ⚙️ 설정")
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

    # --- 핵심: 검색 로직 분리 ---
    if search_query:
        # 1. 필터링 (메모리 내 검색으로 매우 빠름)
        keywords = search_query.split()
        include_words = [w for w in keywords if not w.startswith('!')]
        exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

        # 타겟 컬럼 지정
        target_df = full_df if search_target == "전체" else full_df[[search_target] + ['도로명주소', '충전소명', '운영기관명칭', 'lat', 'lon'] + selected_display_cols]
        
        # 포함 단어 필터링
        filtered_df = full_df.copy()
        for word in include_words:
            if search_target == "전체":
                filtered_df = filtered_df[filtered_df.apply(lambda r: r.astype(str).str.contains(word).any(), axis=1)]
            else:
                filtered_df = filtered_df[filtered_df[search_target].astype(str).str.contains(word)]
        
        # 제외 단어 필터링
        for word in exclude_words:
            filtered_df = filtered_df[~filtered_df.apply(lambda r: r.astype(str).str.contains(word).any(), axis=1)]

        if not filtered_df.empty:
            # 2. 데이터 가공
            filtered_df['충전기대수'] = 1
            if view_mode == "사이트별 통합":
                # 사이트 통합 로직
                group_keys = ['도로명주소', '운영기관명칭']
                agg_rules = {col: 'first' for col in selected_display_cols if col not in group_keys}
                agg_rules['충전기대수'] = 'count'
                agg_rules['lat'] = 'first'
                agg_rules['lon'] = 'first'
                agg_rules['충전소명'] = 'first'
                display_df = filtered_df.groupby(group_keys).agg(agg_rules).reset_index()
                display_df['사이트명'] = display_df['충전소명']
            else:
                display_df = filtered_df
                display_df['사이트명'] = display_df['충전소명']

            # 지표 표시
            m1, m2 = st.columns(2)
            m1.metric("검색 결과 사이트", f"{len(display_df):,} 개")
            m2.metric("총 충전기 수", f"{len(filtered_df):,} 대")

            # 탭 전환 시 검색 반복 없음
            tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])
            
            with tab1:
                st.dataframe(display_df, use_container_width=True)

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
                                popup=f"<b>{row['사이트명']}</b><br>{row['운영기관명칭']}<br>{row['충전기대수']}대"
                            ).add_to(m)
                        st_folium(m, width=None, height=600, use_container_width=True, key="main_map")
                else:
                    st.error("지도 라이브러리가 없습니다.")
        else:
            st.warning("결과가 없습니다.")
    else:
        st.info("검색어를 입력해 주세요.")

except Exception as e:
    st.error(f"오류: {e}")
