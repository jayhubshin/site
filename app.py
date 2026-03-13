import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os

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

# --- 페이지 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")

st.title("🚀 환경부 데이터 통합 검색기")
st.markdown("환경부 데이터를 실시간으로 조회합니다.")

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
    
    # --- UI 레이아웃 ---
    st.divider()
    
    st.subheader("⚙️ 화면 설정")
    view_mode = st.radio("보기 방식 선택", ["상세 데이터 (충전기별)", "통합 데이터 (사이트별)"], horizontal=True)
    
    # 기본 표시 컬럼 설정
    default_cols = ['충전소명', '도로명주소', '상세위치', '충전소구분상세', '운영기관명', '충전용량', '충전기등록일시', '설치년', '설치월']
    actual_default = [c for c in default_cols if c in all_cols]
    
    selected_display_cols = st.multiselect(
        "표시할 컬럼을 선택하세요", 
        options=all_cols, 
        default=actual_default
    )
    
    st.divider()
    
    # --- 검색 설정 ---
    col1, col2 = st.columns([1, 2])
    with col1:
        search_target = st.selectbox("검색할 항목(컬럼) 선택", ["전체"] + all_cols)
    with col2:
        search_query = st.text_input("검색어 입력", placeholder="아파트 이름이나 주소를 입력하세요 (예: 청암1단지)")

    if search_query:
        with st.spinner('데이터 분석 및 사이트 통합 중...'):
            # 검색 쿼리 실행
            if search_target == "전체":
                where_clauses = [f"\"{col}\" LIKE '%{search_query}%'" for col in all_cols]
                sql = f"SELECT * FROM env_data WHERE {' OR '.join(where_clauses)} LIMIT 3000"
            else:
                sql = f"SELECT * FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 3000"
            
            df_result = run_query(sql)

            if not df_result.empty:
                if view_mode == "통합 데이터 (사이트별)":
                    # 주소가 같으면 동일 사이트로 묶는 로직
                    if '도로명주소' in df_result.columns and '충전소명' in df_result.columns:
                        # 주소별 대표 사이트명 매핑
                        site_map = df_result.groupby('도로명주소')['충전소명'].first().to_dict()
                        df_result['사이트명'] = df_result['도로명주소'].map(site_map)
                        
                        # 용량 숫자 변환
                        if '충전용량' in df_result.columns:
                            df_result['충전용량'] = pd.to_numeric(df_result['충전용량'], errors='coerce').fillna(0)
                        
                        # 그룹화 기준 및 집계
                        group_key = ['도로명주소', '사이트명']
                        df_result['충전기대수'] = 1
                        
                        # 집계 규칙 생성
                        agg_rules = {col: 'first' for col in selected_display_cols if col not in group_key}
                        agg_rules['충전기대수'] = 'count'
                        if '충전용량' in df_result.columns:
                            agg_rules['총충전용량(합계)'] = 'sum'
                        
                        final_df = df_result.groupby(group_key).agg(agg_rules).reset_index()
                        
                        # 출력 컬럼 정리
                        cols_to_show = ['사이트명', '충전기대수']
                        if '총충전용량(합계)' in agg_rules:
                            cols_to_show.append('총충전용량(합계)')
                        cols_to_show += [c for c in selected_display_cols if c not in cols_to_show]
                        
                        # 에러 발생 지점 수정 완료
                        st.subheader(f"🔍 통합 검색 결과: {len(final_df):,}개 사이트")
                        st.dataframe(final_df[cols_to_show], width='stretch')
                        target_df = final_df
                    else:
                        st.warning("주소 정보가 부족하여 통합할 수 없습니다.")
                        st.dataframe(df_result[selected_display_cols], width='stretch')
                        target_df = df_result
                else:
                    st.subheader(f"🔍 상세 검색 결과: {len(df_result):,}건")
                    st.dataframe(df_result[selected_display_cols], width='stretch')
                    target_df = df_result

                # CSV 다운로드
                csv = target_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("결과 CSV 저장", data=csv, file_name="search_results.csv")
            else:
                st.warning("검색 결과가 없습니다.")

    else:
        st.info("검색어를 입력하시면 사이트별 통합 결과를 확인하실 수 있습니다.")
        preview = run_query("SELECT * FROM env_data LIMIT 10")
        st.dataframe(preview[selected_display_cols], width='stretch')

except Exception as e:
    st.error(f"시스템 오류 발생: {e}")

st.divider()
st.caption("© 2026 환경부 데이터 검색 대시보드")
