import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re

# 지도 관련 라이브러리 (pip install streamlit-folium folium 필욕)
try:
    from streamlit_folium import st_folium
    import folium
    HAS_MAP_LIBS = True
except ImportError:
    HAS_MAP_LIBS = False

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
        coords = df['위치정보'].astype(str).str.split(',', expand=True)
        if coords.shape[1] >= 2:
            df['lat'] = pd.to_numeric(coords[0], errors='coerce')
            df['lon'] = pd.to_numeric(coords[1], errors='coerce')
    return df

# --- 페이지 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")
prepare_db()

try:
    # 컬럼명 미리 가져오기
    all_cols = run_query("SELECT * FROM env_data LIMIT 1").columns.tolist()
    
    # --- 상단 레이아웃 (3.5:6.5) ---
    header_col, config_col = st.columns([3.5, 6.5])

    with header_col:
        st.title("🚀 환경부 통합 검색 & 지도")
        st.markdown("단어 순서 무관 검색 / 제외어(`!`) 지원 / 개별 마커 지도")

    with config_col:
        st.markdown("##### ⚙️ 보기 방식 및 표시 컬럼 설정")
        inner_col1, inner_col2, inner_col3 = st.columns([1, 2, 1])
        with inner_col1:
            view_mode = st.radio("보기 방식", ["상세 데이터", "사이트별 통합"], horizontal=False)
        with inner_col2:
            default_cols = ['충전소명', '도로명주소', '운영기관명칭', '충전용량', '설치년도', '위치정보']
            actual_default = [c for c in default_cols if c in all_cols]
            selected_display_cols = st.multiselect("표시 컬럼 선택", options=all_cols, default=actual_default)
        with inner_col3:
            map_style = st.selectbox("지도 스타일", ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"])

    st.divider()
    
    # --- 검색 영역 ---
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력", placeholder="예: '산들 !에버온' (단어 순서 무관, !는 제외)")

    if search_query:
        with st.spinner('데이터 분석 및 필터링 중...'):
            # 1. 검색어 파싱
            keywords = search_query.split()
            include_words = [w for w in keywords if not w.startswith('!')]
            exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

            # 2. SQL 1차 검색 (포함 단어 기준 주소 확보)
            if search_target == "전체":
                sub_queries = [f"(도로명주소 LIKE '%{word}%' OR 충전소명 LIKE '%{word}%')" for word in include_words]
                where_clause = " AND ".join(sub_queries) if sub_queries else "1=1"
                sql_primary = f"SELECT 도로명주소 FROM env_data WHERE {where_clause} LIMIT 2000"
            else:
                sub_queries = [f"\"{search_target}\" LIKE '%{word}%'" for word in include_words]
                where_clause = " AND ".join(sub_queries) if sub_queries else "1=1"
                sql_primary = f"SELECT 도로명주소 FROM env_data WHERE {where_clause} LIMIT 2000"
            
            primary_addresses = run_query(sql_primary)

            if not primary_addresses.empty:
                unique_addresses = primary_addresses['도로명주소'].dropna().unique().tolist()
                address_list_str = "', '".join([addr.replace("'", "''") for addr in unique_addresses])
                sql_final = f"SELECT * FROM env_data WHERE 도로명주소 IN ('{address_list_str}')"
                df_raw = run_query(sql_final)

                # 3. 파이썬 정밀 필터링 (제외어 처리 및 전체 텍스트 검사)
                def advanced_filter(row):
                    row_str = " ".join(row.astype(str).values)
                    for w in include_words:
                        if w not in row_str: return False
                    for w in exclude_words:
                        if w in row_str: return False
                    return True

                df_result = df_raw[df_raw.apply(advanced_filter, axis=1)].copy()

                if not df_result.empty:
                    # 기본 정보 생성
                    df_result['충전기대수'] = 1
                    df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                    
                    # 사이트 통합 로직
                    group_cols = ['통합주소']
                    if '운영기관명칭' in df_result.columns: group_cols.append('운영기관명칭')
                    
                    site_names = df_result.groupby(group_cols)['충전소명'].first().reset_index()
                    site_names.rename(columns={'충전소명': '사이트명'}, inplace=True)
                    df_result = pd.merge(df_result, site_names, on=group_cols, how='left')

                    if view_mode == "사이트별 통합":
                        final_group_keys = ['통합주소', '사이트명']
                        if '운영기관명칭' in df_result.columns: final_group_keys.append('운영기관명칭')
                        agg_rules = {col: 'first' for col in selected_display_cols if col not in final_group_keys}
                        agg_rules['충전기대수'] = 'count'
                        if '위치정보' in df_result.columns: agg_rules['위치정보'] = 'first'
                        target_df = df_result.groupby(final_group_keys).agg(agg_rules).reset_index()
                    else:
                        target_df = df_result
                        target_df['사이트명'] = target_df['충전소명']

                    # --- 검색 결과 요약 지표 ---
                    m1, m2 = st.columns(2)
                    m1.metric("검색된 총 사이트 수", f"{len(df_result['통합주소'].unique()):,} 개")
                    m2.metric("검색된 총 충전기 수", f"{len(df_result):,} 대")

                    # --- 결과 탭 ---
                    tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])

                    with tab1:
                        show_cols = ['사이트명', '충전기대수']
                        extra_cols = [c for c in selected_display_cols if c not in show_cols and c in target_df.columns]
                        final_show = show_cols + extra_cols
                        display_df = target_df[final_show].copy()
                        display_df.index = range(1, len(display_df) + 1)
                        st.dataframe(display_df, use_container_width=True)
                        st.download_button("결과 CSV 저장", data=display_df.to_csv(index=False).encode('utf-8-sig'), file_name="search_results.csv")

                    with tab2:
                        if HAS_MAP_LIBS:
                            map_df = parse_lat_lon(target_df.copy()).dropna(subset=['lat', 'lon'])
                            if not map_df.empty:
                                # 지도 생성
                                m = folium.Map(location=[map_df['lat'].mean(), map_df['lon'].mean()], 
                                               zoom_start=12, tiles=map_style)
                                
                                # 모든 점을 개별 CircleMarker로 표시 (합쳐지지 않음)
                                for _, row in map_df.iterrows():
                                    color = 'blue' if '에버온' in str(row['운영기관명칭']) else 'red'
                                    popup_html = f"""
                                    <div style='width:180px; font-size:12px;'>
                                        <b>{row['사이트명']}</b><br>
                                        운영: {row['운영기관명칭']}<br>
                                        충전기: {row.get('충전기대수', 1)}대<br>
                                        주소: {row['도로명주소']}
                                    </div>
                                    """
                                    folium.CircleMarker(
                                        location=[row['lat'], row['lon']],
                                        radius=6,
                                        color=color,
                                        fill=True,
                                        fill_color=color,
                                        fill_opacity=0.6,
                                        popup=folium.Popup(popup_html, max_width=250)
                                    ).add_to(m)
                                
                                st_folium(m, width=None, height=600, use_container_width=True)
                            else:
                                st.warning("위치 정보(좌표)가 포함된 결과가 없습니다.")
                        else:
                            st.error("지도 라이브러리가 설치되지 않았습니다. 터미널에서 'pip install streamlit-folium folium'을 실행하세요.")

            else:
                st.warning("조건에 맞는 검색 결과가 없습니다.")
    else:
        st.info("검색어를 입력하시면 분석 결과와 지도가 나타납니다. (예: 아파트 !에버온)")

except Exception as e:
    st.error(f"시스템 오류 발생: {e}")

st.divider()
st.caption("© 2026 환경부 데이터 검색 서비스 - 고속 엔진 작동 중")
