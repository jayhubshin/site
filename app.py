import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re
from streamlit_folium import st_folium
import folium
from folium.plugins import MarkerCluster

# --- 파일 및 DB 설정 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

def prepare_db():
    if not os.path.exists(DB_NAME):
        if os.path.exists(ZIP_NAME):
            with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
                zip_ref.extractall('./')
        else:
            st.error("데이터 파일을 찾을 수 없습니다.")
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

def parse_lat_lon(df):
    if '위치정보' in df.columns:
        coords = df['위치정보'].str.split(',', expand=True)
        if coords.shape[1] >= 2:
            df['lat'] = pd.to_numeric(coords[0], errors='coerce')
            df['lon'] = pd.to_numeric(coords[1], errors='coerce')
    return df

# --- 페이지 설정 ---
st.set_page_config(page_title="환경부 검색 시스템", layout="wide")
prepare_db()

try:
    all_cols = run_query("SELECT * FROM env_data LIMIT 1").columns.tolist()
    header_col, config_col = st.columns([3.5, 6.5])

    with header_col:
        st.title("🚀 환경부 통합 검색 & 무료지도")
        st.markdown("Folium 기반의 고성능 무료 지도를 사용합니다.")

    with config_col:
        st.markdown("##### ⚙️ 설정")
        inner_col1, inner_col2, inner_col3 = st.columns([1, 1.5, 1.5])
        with inner_col1:
            view_mode = st.radio("보기 방식", ["상세 데이터", "사이트별 통합"])
        with inner_col2:
            default_cols = ['충전소명', '도로명주소', '운영기관명칭', '충전용량', '설치년도', '위치정보']
            selected_display_cols = st.multiselect("컬럼 선택", options=all_cols, default=[c for c in default_cols if c in all_cols])
        with inner_col3:
            map_style = st.selectbox("지도 스타일", ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"])

    st.divider()
    
    # --- 검색 영역 ---
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력 (예: '산들 !에버온')")

    if search_query:
        with st.spinner('검색 및 필터링 중...'):
            keywords = search_query.split()
            include_words = [w for w in keywords if not w.startswith('!')]
            exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

            # 1차 SQL 검색
            sub_queries = [f"(도로명주소 LIKE '%{word}%' OR 충전소명 LIKE '%{word}%')" for word in include_words]
            where_clause = " AND ".join(sub_queries) if sub_queries else "1=1"
            sql = f"SELECT * FROM env_data WHERE {where_clause} LIMIT 2000"
            df_raw = run_query(sql)

            # 제외어 필터링
            if exclude_words:
                for word in exclude_words:
                    df_raw = df_raw[~df_raw.apply(lambda r: r.astype(str).str.contains(word).any(), axis=1)]

            if not df_raw.empty:
                df_raw['충전기대수'] = 1
                df_raw['통합주소'] = df_raw['도로명주소'].apply(extract_base_address)
                
                # 데이터 통합 로직
                if view_mode == "사이트별 통합":
                    group_keys = ['통합주소', '운영기관명칭']
                    agg_rules = {col: 'first' for col in selected_display_cols if col not in group_keys}
                    agg_rules['충전기대수'] = 'count'
                    if '위치정보' in df_raw.columns: agg_rules['위치정보'] = 'first'
                    target_df = df_raw.groupby(group_keys).agg(agg_rules).reset_index()
                    target_df['사이트명'] = target_df['충전소명']
                else:
                    target_df = df_raw
                    target_df['사이트명'] = target_df['충전소명']

                # 상단 지표
                m1, m2 = st.columns(2)
                m1.metric("총 사이트 수", f"{len(target_df):,} 개")
                m2.metric("총 충전기 수", f"{len(df_raw):,} 대")

                tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 Folium 무료 지도"])

                with tab1:
                    display_df = target_df.copy()
                    display_df.index = range(1, len(display_df) + 1)
                    st.dataframe(display_df, use_container_width=True)

                with tab2:
                    map_df = parse_lat_lon(target_df.copy()).dropna(subset=['lat', 'lon'])
                    if not map_df.empty:
                        # 지도 시작 위치 설정
                        m = folium.Map(location=[map_df['lat'].mean(), map_df['lon'].mean()], 
                                       zoom_start=12, tiles=map_style)
                        
                        # 마커 클러스터 (성능 최적화)
                        marker_cluster = MarkerCluster().add_to(m)

                        for _, row in map_df.iterrows():
                            color = 'blue' if '에버온' in str(row['운영기관명칭']) else 'red'
                            popup_text = f"""
                            <div style='width:200px'>
                                <b>{row['사이트명']}</b><br>
                                운영: {row['운영기관명칭']}<br>
                                충전기: {row.get('충전기대수', 1)}대<br>
                                주소: {row['도로명주소']}
                            </div>
                            """
                            folium.Marker(
                                location=[row['lat'], row['lon']],
                                popup=folium.Popup(popup_text, max_width=300),
                                icon=folium.Icon(color=color, icon='info-sign'),
                            ).add_to(marker_cluster)

                        st_folium(m, width=None, height=500, use_container_width=True)
                    else:
                        st.warning("위치 정보가 없습니다.")
            else:
                st.warning("검색 결과가 없습니다.")

except Exception as e:
    st.error(f"오류 발생: {e}")
