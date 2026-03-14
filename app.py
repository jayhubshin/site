import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re
import pydeck as pdk

# --- 파일 및 DB 설정 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

@st.cache_resource
def prepare_db():
    if not os.path.exists(DB_NAME):
        if os.path.exists(ZIP_NAME):
            with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
                zip_ref.extractall('./')
        else:
            st.error("데이터 파일(data.db 또는 data.db.zip)을 찾을 수 없습니다.")
            st.stop()

def run_query(query):
    with sqlite3.connect(DB_NAME, check_same_thread=False) as conn:
        return pd.read_sql_query(query, conn)

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

@st.cache_data
def get_column_names():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
        return [description[0] for description in cursor.description]

try:
    all_cols = get_column_names()
    header_col, config_col = st.columns([3.5, 6.5])

    with header_col:
        st.title("🚀 환경부 통합 검색 & 지도")
        st.markdown("단어 순서 무관 검색 가능 / 제외어(`!`) 지원")

    with config_col:
        st.markdown("##### ⚙️ 설정")
        inner_col1, inner_col2 = st.columns([1, 2.5])
        with inner_col1:
            # 1. 기본 보기 방식을 '사이트별 통합'으로 설정
            view_mode = st.radio("보기 방식", ["사이트별 통합", "상세 데이터"], horizontal=False)
        with inner_col2:
            # 2. 요청하신 기본 표시 컬럼 순서 설정
            requested_cols = ['사이트명', '충전기대수', '충전소명', '도로명주소', '운영기관명칭', '충전용량', '운영개시일', '설치년도']
            actual_default = [c for c in requested_cols if c in all_cols or c in ['사이트명', '충전기대수']]
            selected_display_cols = st.multiselect("표시할 컬럼 설정", options=all_cols + ['사이트명', '충전기대수'], default=actual_default)

    st.divider()
    
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력", placeholder="예: '산들 !에버온' (산들 포함, 에버온 제외)")

    if search_query:
        with st.spinner('데이터 분석 중...'):
            keywords = search_query.split()
            include_words = [w for w in keywords if not w.startswith('!')]
            exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

            # SQL 최적화 쿼리
            target_field = "도로명주소" if search_target == "전체" else f"\"{search_target}\""
            search_field = "도로명주소" if search_target == "전체" else f"\"{search_target}\""
            
            sub_queries = [f"(도로명주소 LIKE '%{word}%' OR 충전소명 LIKE '%{word}%')" if search_target == "전체" 
                           else f"\"{search_target}\" LIKE '%{word}%'" for word in include_words]
            where_clause = " AND ".join(sub_queries) if sub_queries else "1=1"
            
            sql_primary = f"SELECT 도로명주소 FROM env_data WHERE {where_clause} LIMIT 2000"
            primary_addresses = run_query(sql_primary)

            if not primary_addresses.empty:
                unique_addresses = primary_addresses['도로명주소'].dropna().unique().tolist()
                address_list_str = "', '".join([addr.replace("'", "''") for addr in unique_addresses])
                df_raw = run_query(f"SELECT * FROM env_data WHERE 도로명주소 IN ('{address_list_str}')")

                # 정밀 필터링
                def advanced_filter(row):
                    row_str = " ".join(row.astype(str).values)
                    return all(w in row_str for w in include_words) and not any(w in row_str for w in exclude_words)

                df_result = df_raw[df_raw.apply(advanced_filter, axis=1)].copy()

                if not df_result.empty:
                    df_result['충전기대수'] = 1
                    df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                    
                    # 사이트명 매칭
                    group_keys = ['통합주소', '운영기관명칭'] if '운영기관명칭' in df_result.columns else ['통합주소']
                    site_names = df_result.groupby(group_keys)['충전소명'].first().reset_index()
                    site_names.rename(columns={'충전소명': '사이트명'}, inplace=True)
                    df_result = pd.merge(df_result, site_names, on=group_keys, how='left')

                    if view_mode == "사이트별 통합":
                        agg_rules = {col: 'first' for col in df_result.columns if col not in group_keys + ['사이트명', '충전기대수']}
                        agg_rules['충전기대수'] = 'count'
                        target_df = df_result.groupby(group_keys + ['사이트명']).agg(agg_rules).reset_index()
                    else:
                        target_df = df_result.copy()

                    # --- 결과 요약 ---
                    m1, m2 = st.columns(2)
                    m1.metric("검색된 총 사이트", f"{len(df_result['통합주소'].unique()):,} 개")
                    m2.metric("검색된 총 충전기", f"{len(df_result):,} 대")

                    tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])

                    with tab1:
                        # 3. 데이터프레임 스타일링 (배경색 및 정렬)
                        def style_rows(row):
                            if '에버온' in str(row['운영기관명칭']):
                                return ['background-color: #E3F2FD'] * len(row)  # 옅은 파랑
                            return ['background-color: #FFEBEE'] * len(row)      # 옅은 빨강

                        # 컬럼 순서 재배치 및 인덱스 설정
                        final_cols = [c for c in selected_display_cols if c in target_df.columns]
                        display_df = target_df[final_cols].copy()
                        display_df.index = range(1, len(display_df) + 1)

                        # 스타일 적용
                        styled_df = display_df.style.apply(style_rows, axis=1).set_properties(
                            subset=['충전기대수'] if '충전기대수' in display_df.columns else [], 
                            **{'text-align': 'center'} # 4. 충전기대수 가운데 정렬
                        )

                        st.dataframe(styled_df, use_container_width=True)
                        st.download_button("결과 CSV 저장", data=display_df.to_csv(index=False).encode('utf-8-sig'), file_name="search_results.csv")

                    with tab2:
                        map_df = parse_lat_lon(target_df.copy()).dropna(subset=['lat', 'lon'])
                        if not map_df.empty:
                            map_df['color'] = map_df['운영기관명칭'].apply(lambda x: [0, 150, 255, 160] if '에버온' in str(x) else [255, 80, 80, 160])
                            view_state = pdk.ViewState(latitude=map_df['lat'].mean(), longitude=map_df['lon'].mean(), zoom=11)
                            layer = pdk.Layer("ScatterplotLayer", map_df, get_position='[lon, lat]', 
                                              get_color='color', get_radius=60, pickable=True)
                            st.pydeck_chart(pdk.Deck(map_style="mapbox://styles/mapbox/light-v10", layers=[layer], initial_view_state=view_state, 
                                                    tooltip={"html": "<b>{사이트명}</b><br/>{운영기관명칭}<br/>충전기: {충전기대수}대"}))
                else:
                    st.warning("조건에 맞는 결과가 없습니다.")
            else:
                st.warning("검색 결과가 없습니다.")
    else:
        st.info("검색어를 입력하세요.")

except Exception as e:
    st.error(f"오류 발생: {e}")
