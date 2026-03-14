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
    if '위치정보' in df.columns:
        coords = df['위치정보'].astype(str).str.replace(' ', '').str.split(',', expand=True)
        if coords.shape[1] >= 2:
            df['lat'] = pd.to_numeric(coords[0], errors='coerce')
            df['lon'] = pd.to_numeric(coords[1], errors='coerce')
            df = df.dropna(subset=['lat', 'lon'])
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

# --- 3. 메인 로직 시작 ---
try:
    all_cols = get_column_names()
    st.title("🚀 환경부 통합 검색 & 통계 시스템")
    
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력 (예: '산들 !에버온')", placeholder="검색어를 입력하고 엔터를 누르세요.")

    if search_query:
        with st.spinner('데이터 분석 중...'):
            keywords = search_query.split()
            include_words = [w for w in keywords if not w.startswith('!')]
            exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

            base_word = include_words[0] if include_words else ""
            sql = f"SELECT * FROM env_data WHERE (도로명주소 LIKE '%{base_word}%' OR 충전소명 LIKE '%{base_word}%' OR 운영기관명칭 LIKE '%{base_word}%')"
            df_raw = run_query(sql)

            def advanced_filter(row):
                row_str = " ".join(row.astype(str).values)
                return all(w in row_str for w in include_words) and not any(w in row_str for w in exclude_words)

            df_result = df_raw[df_raw.apply(advanced_filter, axis=1)].copy()

            if not df_result.empty:
                # 공통 가공
                df_result['충전기대수'] = 1
                df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                
                group_keys = ['통합주소', '운영기관명칭']
                site_map = df_result.groupby(group_keys)['충전소명'].first().reset_index()
                site_map.rename(columns={'충전소명': '사이트명'}, inplace=True)
                df_result = pd.merge(df_result, site_map, on=group_keys, how='left')

                # 사이트별 통합 데이터 집계
                agg_dict = {col: 'first' for col in df_result.columns if col not in group_keys + ['사이트명', '충전기대수']}
                agg_dict['충전기대수'] = 'count'
                target_df = df_result.groupby(group_keys + ['사이트명']).agg(agg_dict).reset_index()

                # --- 요약 지표 ---
                m1, m2 = st.columns(2)
                m1.metric("🏠 검색된 사이트 수", f"{len(target_df):,} 개")
                m2.metric("🔌 검색된 총 충전기 수", f"{target_df['충전기대수'].sum():,} 대")

                # --- 결과 탭 ---
                tab1, tab2, tab3 = st.tabs(["📊 검색결과 목록", "📍 지도 분포", "🏢 운영기관별 통계"])

                with tab1:
                    # 기본 표시 컬럼에 '충전기등록일시' 추가
                    requested_cols = ['사이트명', '충전기대수', '충전소명', '도로명주소', '운영기관명칭', '충전용량', '충전기등록일시', '설치년도']
                    display_options = ['사이트명', '충전기대수'] + [c for c in all_cols if c not in ['사이트명', '충전기대수']]
                    actual_default = [c for c in requested_cols if c in display_options]
                    selected_cols = st.multiselect("📋 표시 컬럼 수정:", options=display_options, default=actual_default)

                    def style_rows(row):
                        color = '#E3F2FD' if '에버온' in str(row['운영기관명칭']) else '#FFEBEE'
                        return [f'background-color: {color}'] * len(row)

                    final_df = target_df[[c for c in selected_cols if c in target_df.columns]].copy()
                    final_df.index = range(1, len(final_df) + 1)
                    styled_df = final_df.style.apply(style_rows, axis=1)
                    if '충전기대수' in final_df.columns:
                        styled_df = styled_df.set_properties(subset=['충전기대수'], **{'text-align': 'center'})
                    st.dataframe(styled_df, use_container_width=True)

              with tab2:
                    map_df = parse_lat_lon(target_df.copy())
                    if not map_df.empty:
                        # 1. 숫자를 문자열로 변환 (필수)
                        map_df['count_text'] = map_df['충전기대수'].astype(str)
                        
                        # 2. 색상 및 반지름 설정
                        map_df['color'] = map_df['운영기관명칭'].apply(
                            lambda x: [0, 102, 204, 230] if '에버온' in str(x) else [220, 30, 30, 230]
                        )
                        # 원 크기 (글자가 들어갈 충분한 공간 확보)
                        map_df['radius'] = 60 + (map_df['충전기대수'] * 12)
                        
                        # 3. 레이어 설정
                        # (1) 배경 원 레이어
                        scatterplot_layer = pdk.Layer(
                            "ScatterplotLayer",
                            map_df,
                            get_position='[lon, lat]',
                            get_color='color',
                            get_radius='radius',
                            radius_min_pixels=18,  # 글씨가 잘 안 보이지 않도록 최소 크기 상향
                            radius_max_pixels=45,
                            pickable=True,
                            stroked=True,
                            line_width_min_pixels=1,
                            get_line_color=[255, 255, 255]
                        )
                        
                        # (2) 숫자 텍스트 레이어 (원보다 나중에 정의하여 위로 올림)
                        text_layer = pdk.Layer(
                            "TextLayer",
                            map_df,
                            get_position='[lon, lat]',
                            get_text='count_text',
                            get_color=[255, 255, 255], # 흰색 글자
                            get_size=20,               # 글자 크기 대폭 상향
                            size_scale=1,              # 줌에 따른 크기 유지
                            get_alignment_baseline="'center'",
                            get_text_anchor="'middle'",
                            font_family="'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif",
                            font_weight=900,           # 가장 굵게
                            outline_width=2,           # 글자 테두리 추가 (가독성 핵심)
                            outline_color=[0, 0, 0]    # 검은색 테두리
                        )
                        
                        st.pydeck_chart(pdk.Deck(
                            map_style="light",
                            initial_view_state=pdk.ViewState(
                                latitude=map_df['lat'].median(),
                                longitude=map_df['lon'].median(),
                                zoom=14
                            ),
                            # 레이어 순서 중요: 뒤에 있는 것이 위로 올라옵니다.
                            layers=[scatterplot_layer, text_layer],
                            tooltip={"html": "<b>{사이트명}</b><br/>{운영기관명칭}<br/>충전기: {충전기대수}대"}
                        ))
                    else:
                        st.warning("지도에 표시할 유효한 좌표가 없습니다.")
                with tab3:
                    st.subheader("🏢 운영기관별 요약 통계")
                    # 운영기관명칭별 사이트수 및 충전기수 집계
                    op_summary = df_result.groupby('운영기관명칭').agg(
                        사이트수=('사이트명', 'nunique'),
                        총충전기수=('충전기대수', 'sum')
                    ).reset_index().sort_values(by='총충전기수', ascending=False)
                    
                    st.dataframe(op_summary, use_container_width=True, hide_index=True)

                    # --- 연도별 운영기관 추이로 변경 ---
                    st.divider()
                    st.subheader("📅 연도별 운영기관 설치 추이")
                    if '설치년도' in df_result.columns:
                        # 설치년도 데이터 정제
                        df_result['설치년도_clean'] = df_result['설치년도'].astype(str).str.extract(r'(\d{4})')
                        
                        # 연도별-운영기관별로 그룹화 순서 변경
                        year_op_summary = df_result.groupby(['설치년도_clean', '운영기관명칭']).agg(
                            충전기수=('충전기대수', 'sum'),
                            사이트수=('사이트명', 'nunique')
                        ).reset_index()
                        
                        # 최신 연도 순, 충전기 많은 순으로 정렬
                        year_op_summary = year_op_summary.sort_values(
                            by=['설치년도_clean', '충전기수'], 
                            ascending=[False, False]
                        )
                        
                        # 컬럼명 정리 및 출력
                        year_op_summary.columns = ['설치년도', '운영기관명칭', '충전기수', '사이트수']
                        st.write("각 연도별로 가장 많이 설치한 운영기관 순으로 표시됩니다.")
                        st.dataframe(year_op_summary, use_container_width=True, hide_index=True)
                        
                        # (선택 사항) 피벗 테이블 형태로 보고 싶을 경우 아래 코드 추가 가능
                        # st.write("📊 연도별 운영기관 설치 현황 (피벗 테이블)")
                        # pivot_df = year_op_summary.pivot(index='설치년도', columns='운영기관명칭', values='충전기수').fillna(0)
                        # st.dataframe(pivot_df)
                    else:
                        st.info("데이터에 '설치년도' 정보가 없습니다.")

            else:
                st.warning("결과가 없습니다.")
    else:
        st.info("검색어를 입력하세요.")

except Exception as e:
    st.error(f"오류 발생: {e}")
