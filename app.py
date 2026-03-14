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
    """DB 파일 추출 및 초기화"""
    if not os.path.exists(DB_NAME):
        if os.path.exists(ZIP_NAME):
            with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
                zip_ref.extractall('./')
        else:
            st.error("데이터 파일(data.db 또는 data.db.zip)을 찾을 수 없습니다.")
            st.stop()

def run_query(query):
    """SQL 엔진을 사용하여 데이터 로드"""
    with sqlite3.connect(DB_NAME, check_same_thread=False) as conn:
        return pd.read_sql_query(query, conn)

def extract_base_address(address):
    """사이트 통합을 위한 주소 정규화"""
    if not address: return ""
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

def parse_lat_lon(df):
    """위치정보 문자열을 위경도 숫자로 변환"""
    if '위치정보' in df.columns:
        coords = df['위치정보'].astype(str).str.split(',', expand=True)
        if coords.shape[1] >= 2:
            df['lat'] = pd.to_numeric(coords[0], errors='coerce')
            df['lon'] = pd.to_numeric(coords[1], errors='coerce')
    return df

# --- 2. 앱 기본 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")
prepare_db()

# 세션 상태 초기화
if 'df_result' not in st.session_state:
    st.session_state.df_result = None

@st.cache_data
def get_column_names():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
        return [description[0] for description in cursor.description]

try:
    all_cols = get_column_names()
    
    # --- 3. 헤더 및 설정 영역 ---
    st.title("🚀 환경부 통합 검색 & 지도")
    
    # 설정 박스 (Expander를 사용하여 UI 정리)
    with st.expander("⚙️ 보기 방식 및 지도 테마 설정", expanded=True):
        c1, c2, c3 = st.columns([1.2, 3, 1.5])
        
        with c1:
            # 기본 보기 방식: 사이트별 통합
            view_mode = st.radio("보기 방식", ["사이트별 통합", "상세 데이터"], horizontal=False)
        
        with c2:
            # 요청하신 컬럼 순서 배치
            requested_cols = ['사이트명', '충전기대수', '충전소명', '도로명주소', '운영기관명칭', '충전용량', '운영개시일', '설치년도']
            actual_default = [c for c in requested_cols if c in all_cols or c in ['사이트명', '충전기대수']]
            selected_display_cols = st.multiselect("표시 컬럼 설정", options=['사이트명', '충전기대수'] + all_cols, default=actual_default)
            
        with c3:
            # 지도 밝기/테마 조절 단추
            map_theme_label = st.selectbox("🗺️ 지도 밝기 (테마)", [
                "Road (눈이 편한 스타일)", 
                "Silver (깔끔한 회색조)",
                "Light (매우 밝음)", 
                "Dark (야간 모드)"
            ], index=0)
            
            theme_dict = {
                "Road (눈이 편한 스타일)": "mapbox://styles/mapbox/streets-v11",
                "Silver (깔끔한 회색조)": "mapbox://styles/mapbox/light-v9",
                "Light (매우 밝음)": "mapbox://styles/mapbox/light-v10",
                "Dark (야간 모드)": "mapbox://styles/mapbox/dark-v10"
            }

    st.divider()
    
    # --- 4. 검색창 ---
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력 (예: '산들 !에버온')", placeholder="단어 순서 무관 검색 / 제외어(!) 지원")

    if search_query:
        with st.spinner('데이터 필터링 중...'):
            keywords = search_query.split()
            include_words = [w for w in keywords if not w.startswith('!')]
            exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

            # SQL 검색 조건 생성
            where_clauses = []
            for word in include_words:
                if search_target == "전체":
                    where_clauses.append(f"(도로명주소 LIKE '%{word}%' OR 충전소명 LIKE '%{word}%' OR 운영기관명칭 LIKE '%{word}%')")
                else:
                    where_clauses.append(f"\"{search_target}\" LIKE '%{word}%'")
            
            sql_where = " AND ".join(where_clauses) if where_clauses else "1=1"
            sql_final = f"SELECT * FROM env_data WHERE {sql_where} LIMIT 3000"
            
            df_raw = run_query(sql_final)

            # 정밀 필터링 (제외어 적용)
            def advanced_filter(row):
                row_str = " ".join(row.astype(str).values)
                return all(w in row_str for w in include_words) and not any(w in row_str for w in exclude_words)

            df_result = df_raw[df_raw.apply(advanced_filter, axis=1)].copy()

            if not df_result.empty:
                # 데이터 가공 및 집계
                df_result['충전기대수'] = 1
                df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                
                # 운영기관별 사이트명 생성
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

                # 지표 요약
                m1, m2 = st.columns(2)
                m1.metric("검색된 총 사이트", f"{len(df_result['통합주소'].unique()):,} 개")
                m2.metric("검색된 총 충전기", f"{len(df_result):,} 대")

                # 결과 탭 구성
                tab1, tab2 = st.tabs(["📊 데이터 목록", "📍 지도 분포"])

                with tab1:
                    # 행 색상 지정 함수 (에버온: 하늘색, 기타: 분홍색)
                    def style_rows(row):
                        if '에버온' in str(row['운영기관명칭']):
                            return ['background-color: #E3F2FD'] * len(row)
                        return ['background-color: #FFEBEE'] * len(row)

                    # 컬럼 필터링 및 인덱스 재설정
                    final_cols = [c for c in selected_display_cols if c in target_df.columns]
                    display_df = target_df[final_cols].copy()
                    display_df.index = range(1, len(display_df) + 1)

                    # 스타일 적용 (색상 + 가운데 정렬)
                    styled_df = display_df.style.apply(style_rows, axis=1)
                    if '충전기대수' in display_df.columns:
                        styled_df = styled_df.set_properties(subset=['충전기대수'], **{'text-align': 'center'})

                    st.dataframe(styled_df, use_container_width=True)
                    st.download_button("결과 CSV 저장", data=display_df.to_csv(index=False).encode('utf-8-sig'), file_name="search_results.csv")

                with tab2:
                    map_df = parse_lat_lon(target_df.copy()).dropna(subset=['lat', 'lon'])
                    if not map_df.empty:
                        # 점 색상: 에버온(진파랑), 기타(진빨강)
                        map_df['color'] = map_df['운영기관명칭'].apply(
                            lambda x: [0, 102, 204, 200] if '에버온' in str(x) else [204, 0, 0, 200]
                        )
                        
                        view_state = pdk.ViewState(
                            latitude=map_df['lat'].mean(), 
                            longitude=map_df['lon'].mean(), 
                            zoom=11
                        )
                        
                        layer = pdk.Layer(
                            "ScatterplotLayer", 
                            map_df, 
                            get_position='[lon, lat]', 
                            get_color='color', 
                            get_radius=80, 
                            pickable=True,
                            stroked=True,
                            line_width_min_pixels=1,
                            get_line_color=[255, 255, 255]
                        )
                        
                        st.pydeck_chart(pdk.Deck(
                            map_style=theme_dict[map_theme_label], # 사용자가 선택한 밝기/테마 적용
                            layers=[layer], 
                            initial_view_state=view_state, 
                            tooltip={"html": "<b>{사이트명}</b><br/>{운영기관명칭}<br/>충전기: {충전기대수}대"}
                        ))
                    else:
                        st.warning("위치 정보가 없습니다.")
            else:
                st.warning("검색 결과가 없습니다.")
    else:
        st.info("검색어를 입력하여 조회를 시작하세요.")

except Exception as e:
    st.error(f"오류가 발생했습니다: {e}")
