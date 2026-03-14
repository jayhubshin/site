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
    """위경도 파싱 및 한국 범위 유효성 검사 (백지 현상 방지)"""
    if '위치정보' in df.columns:
        # 공백 제거 및 콤마 기준 분리
        coords = df['위치정보'].astype(str).str.replace(' ', '').str.split(',', expand=True)
        if coords.shape[1] >= 2:
            df['lat'] = pd.to_numeric(coords[0], errors='coerce')
            df['lon'] = pd.to_numeric(coords[1], errors='coerce')
            df = df.dropna(subset=['lat', 'lon'])
            # 한국 인근 좌표만 필터링 (위도 33~39, 경도 124~132)
            df = df[(df['lat'] > 32) & (df['lat'] < 40) & (df['lon'] > 124) & (df['lon'] < 132)]
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
    
    # --- 3. 설정 영역 ---
    with st.expander("⚙️ 보기 방식 및 컬럼 설정", expanded=True):
        c1, c2 = st.columns([1, 3])
        with c1:
            view_mode = st.radio("보기 방식", ["사이트별 통합", "상세 데이터"], index=0)
        with c2:
            requested_cols = ['사이트명', '충전기대수', '충전소명', '도로명주소', '운영기관명칭', '충전용량', '운영개시일', '설치년도']
            display_options = ['사이트명', '충전기대수'] + [c for c in all_cols if c not in ['사이트명', '충전기대수']]
            actual_default = [c for c in requested_cols if c in display_options]
            selected_display_cols = st.multiselect("표시 컬럼", options=display_options, default=actual_default)

    st.divider()
    
    # --- 4. 검색창 ---
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력 (예: '산들 !에버온')", placeholder="검색어를 입력하고 엔터를 누르세요.")

    if search_query:
        with st.spinner('데이터 조회 중...'):
            keywords = search_query.split()
            include_words = [w for w in keywords if not w.startswith('!')]
            exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

            # SQL 기초 검색 (첫 번째 단어 기준)
            base_word = include_words[0] if include_words else ""
            sql = f"SELECT * FROM env_data WHERE (도로명주소 LIKE '%{base_word}%' OR 충전소명 LIKE '%{base_word}%' OR 운영기관명칭 LIKE '%{base_word}%') LIMIT 5000"
            df_raw = run_query(sql)

            # 상세 필터링 (순서 무관 포함 및 제외어 적용)
            def advanced_filter(row):
                row_str = " ".join(row.astype(str).values)
                return all(w in row_str for w in include_words) and not any(w in row_str for w in exclude_words)

            df_result = df_raw[df_raw.apply(advanced_filter, axis=1)].copy()

            if not df_result.empty:
                # 사이트명 및 충전기대수 생성 로직
                df_result['충전기대수'] = 1
                df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                
                # 운영기관별 사이트명 매칭
                group_keys = ['통합주소', '운영기관명칭']
                site_map = df_result.groupby(group_keys)['충전소명'].first().reset_index()
                site_map.rename(columns={'충전소명': '사이트명'}, inplace=True)
                df_result = pd.merge(df_result, site_map, on=group_keys, how='left')

                # 보기 모드 적용
                if view_mode == "사이트별 통합":
                    agg_dict = {col: 'first' for col in df_result.columns if col not in group_keys + ['사이트명', '충전기대수']}
                    agg_dict['충전기대수'] = 'count'
                    target_df = df_result.groupby(group_keys + ['사이트명']).agg(agg_dict).reset_index()
                else:
                    target_df = df_result.copy()

                # --- 결과 출력 ---
                tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])

                with tab1:
                    # 행 색상 스타일 (에버온: 하늘색, 기타: 분홍색)
                    def style_rows(row):
                        color = '#E3F2FD' if '에버온' in str(row['운영기관명칭']) else '#FFEBEE'
                        return [f'background-color: {color}'] * len(row)

                    final_cols = [c for c in selected_display_cols if c in target_df.columns]
                    display_df = target_df[final_cols].copy()
                    display_df.index = range(1, len(display_df) + 1)

                    styled_df = display_df.style.apply(style_rows, axis=1)
                    if '충전기대수' in display_df.columns:
                        styled_df = styled_df.set_properties(subset=['충전기대수'], **{'text-align': 'center'})

                    st.dataframe(styled_df, use_container_width=True)

                with tab2:
                    map_df = parse_lat_lon(target_df.copy())
                    if not map_df.empty:
                        # 점 색상: 에버온(진파랑), 기타(진빨강)
                        map_df['color'] = map_df['운영기관명칭'].apply(
                            lambda x: [0, 102, 204, 220] if '에버온' in str(x) else [204, 0, 0, 220]
                        )
                        
                        # 지도 설정: 스타일 'light' 고정
                        st.pydeck_chart(pdk.Deck(
                            map_style="light",  # 요청하신 기본 주간 스타일
                            initial_view_state=pdk.ViewState(
                                latitude=map_df['lat'].median(),
                                longitude=map_df['lon'].median(),
                                zoom=10,
                                pitch=0
                            ),
                            layers=[pdk.Layer(
                                "ScatterplotLayer",
                                map_df,
                                get_position='[lon, lat]',
                                get_color='color',
                                get_radius=120,
                                pickable=True,
                                stroked=True,
                                line_width_min_pixels=1,
                                get_line_color=[255, 255, 255]
                            )],
                            tooltip={"html": "<b>{사이트명}</b><br/>{운영기관명칭}<br/>충전기: {충전기대수}대"}
                        ))
                    else:
                        st.warning("유효한 좌표 정보가 없어 지도를 표시할 수 없습니다.")
            else:
                st.warning("결과가 없습니다.")
except Exception as e:
    st.error(f"오류: {e}")
