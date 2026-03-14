import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re
import pydeck as pdk  # 고급 지도 시각화를 위해 추가

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
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")
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
    header_col, config_col = st.columns([3.5, 6.5])

    with header_col:
        st.title("🚀 환경부 통합 검색 & 지도")
        st.markdown("에버온은 **파란색**, 나머지는 **빨간색**으로 표시됩니다.")

    with config_col:
        st.markdown("##### ⚙️ 보기 방식 및 표시 컬럼 설정")
        inner_col1, inner_col2 = st.columns([1, 2.5])
        with inner_col1:
            view_mode = st.radio("보기 방식", ["상세 데이터", "사이트별 통합"], horizontal=False)
        with inner_col2:
            default_cols = ['충전소명', '도로명주소', '운영기관명칭', '충전용량', '설치년도', '위치정보']
            actual_default = [c for c in default_cols if c in all_cols]
            selected_display_cols = st.multiselect("표시할 컬럼을 선택하세요", options=all_cols, default=actual_default)

    st.divider()
    
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력", placeholder="아파트 이름이나 주소를 입력하세요")

    if search_query:
        with st.spinner('위치 데이터 분석 중...'):
            if search_target == "전체":
                where_clauses = [f"\"{col}\" LIKE '%{search_query}%'" for col in all_cols]
                sql_primary = f"SELECT 도로명주소 FROM env_data WHERE {' OR '.join(where_clauses)} LIMIT 1000"
            else:
                sql_primary = f"SELECT 도로명주소 FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 1000"
            
            primary_addresses = run_query(sql_primary)

            if not primary_addresses.empty:
                unique_addresses = primary_addresses['도로명주소'].dropna().unique().tolist()
                address_list_str = "', '".join([addr.replace("'", "''") for addr in unique_addresses])
                sql_final = f"SELECT * FROM env_data WHERE 도로명주소 IN ('{address_list_str}')"
                df_result = run_query(sql_final)

                # 데이터 처리
                df_result['충전기대수'] = 1
                if view_mode == "사이트별 통합":
                    df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                    group_cols = ['통합주소']
                    if '운영기관명칭' in df_result.columns: group_cols.append('운영기관명칭')
                    
                    site_names = df_result.groupby(group_cols)['충전소명'].first().reset_index()
                    site_names.rename(columns={'충전소명': '사이트명'}, inplace=True)
                    df_result = pd.merge(df_result, site_names, on=group_cols, how='left')
                    
                    final_group_keys = ['통합주소', '사이트명']
                    if '운영기관명칭' in df_result.columns: final_group_keys.append('운영기관명칭')
                            
                    agg_rules = {col: 'first' for col in selected_display_cols if col not in final_group_keys}
                    agg_rules['충전기대수'] = 'count'
                    target_df = df_result.groupby(final_group_keys).agg(agg_rules).reset_index()
                else:
                    target_df = df_result
                    if '충전소명' in target_df.columns:
                        target_df['사이트명'] = target_df['충전소명']

                tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])

                with tab1:
                    show_cols = ['사이트명', '충전기대수']
                    extra_cols = [c for c in selected_display_cols if c not in show_cols and c in target_df.columns]
                    final_show = show_cols + extra_cols
                    display_df = target_df[final_show].copy()
                    display_df.index = range(1, len(display_df) + 1)
                    st.dataframe(display_df, use_container_width=True)

                with tab2:
                    st.subheader("📍 충전소 위치 시각화 (마우스를 점 위에 올려보세요)")
                    map_df = parse_lat_lon(target_df.copy()).dropna(subset=['lat', 'lon'])
                    
                    if not map_df.empty:
                        # 색상 로직: 에버온 파란색 [0, 0, 255], 나머지 빨간색 [255, 0, 0]
                        map_df['color_r'] = map_df['운영기관명칭'].apply(lambda x: 0 if '에버온' in str(x) else 255)
                        map_df['color_b'] = map_df['운영기관명칭'].apply(lambda x: 255 if '에버온' in str(x) else 0)
                        
                        view_state = pdk.ViewState(
                            latitude=map_df['lat'].mean(),
                            longitude=map_df['lon'].mean(),
                            zoom=11, pitch=0
                        )

                        layer = pdk.Layer(
                            "ScatterplotLayer",
                            map_df,
                            get_position='[lon, lat]',
                            get_color='[color_r, 0, color_b, 160]',
                            get_radius=150,
                            pickable=True,
                        )

                        tooltip = {
                            "html": "<b>충전소명:</b> {사이트명}<br/>"
                                    "<b>운영기관:</b> {운영기관명칭}<br/>"
                                    "<b>충전기 수:</b> {충전기대수}대",
                            "style": {"backgroundColor": "steelblue", "color": "white"}
                        }

                        st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip=tooltip))
                    else:
                        st.warning("위치 정보가 포함된 데이터가 없습니다.")

except Exception as e:
    st.error(f"시스템 오류 발생: {e}")

st.divider()
st.caption("© 2026 환경부 데이터 검색 대시보드")
