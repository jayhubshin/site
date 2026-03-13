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
    
    st.divider()
    st.subheader("⚙️ 화면 설정")
    view_mode = st.radio("보기 방식 선택", ["상세 데이터 (충전기별)", "통합 데이터 (사이트별)"], horizontal=True)
    
    default_cols = ['충전소명', '도로명주소', '상세위치', '충전소구분상세', '운영기관명', '충전용량', '충전기등록일시', '설치년', '설치월']
    actual_default = [c for c in default_cols if c in all_cols]
    
    selected_display_cols = st.multiselect(
        "표시할 컬럼을 선택하세요", 
        options=all_cols, 
        default=actual_default
    )
    
    st.divider()
    
    col1, col2 = st.columns([1, 2])
    with col1:
        search_target = st.selectbox("검색할 항목(컬럼) 선택", ["전체"] + all_cols)
    with col2:
        search_query = st.text_input("검색어 입력", placeholder="아파트 이름이나 주소를 입력하세요 (예: 청암1단지)")

    if search_query:
        with st.spinner('데이터 분석 중...'):
            if search_target == "전체":
                where_clauses = [f"\"{col}\" LIKE '%{search_query}%'" for col in all_cols]
                sql = f"SELECT * FROM env_data WHERE {' OR '.join(where_clauses)} LIMIT 3000"
            else:
                sql = f"SELECT * FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 3000"
            
            df_result = run_query(sql)

            if not df_result.empty:
                if view_mode == "통합 데이터 (사이트별)":
                    if '도로명주소' in df_result.columns and '충전소명' in df_result.columns:
                        # 1. 주소 기반 사이트명 매핑 (동일 주소의 첫 번째 충전소명을 대표 사이트명으로 사용)
                        site_map = df_result.groupby('도로명주소')['충전소명'].first().to_dict()
                        df_result['사이트명'] = df_result['도로명주소'].map(site_map)
                        
                        # 2. 집계 설정
                        df_result['충전기대수'] = 1
                        group_key = ['도로명주소', '사이트명']
                        
                        # 선택된 컬럼 중 그룹키가 아닌 것들만 대표값(first)으로 집계
                        agg_rules = {col: 'first' for col in selected_display_cols if col not in group_key}
                        agg_rules['충전기대수'] = 'count'
                        
                        final_df = df_result.groupby(group_key).agg(agg_rules).reset_index()
                        
                        # 3. 컬럼 표시 순서 정리 (사이트명, 충전기대수를 맨 앞으로)
                        show_cols = ['사이트명', '충전기대수']
                        extra_cols = [c for c in selected_display_cols if c not in show_cols and c in final_df.columns]
                        final_show = show_cols + extra_cols
                        
                        st.subheader(f"🔍 통합 검색 결과: {len(final_df):,}개 사이트")
                        st.dataframe(final_df[final_show], width='stretch')
                        target_df = final_df[final_show]
                    else:
                        st.warning("주소 또는 충전소명 컬럼이 없어 통합할 수 없습니다.")
                        st.dataframe(df_result[selected_display_cols], width='stretch')
                        target_df = df_result
                else:
                    st.subheader(f"🔍 상세 검색 결과: {len(df_result):,}건")
                    st.dataframe(df_result[selected_display_cols], width='stretch')
                    target_df = df_result

                # CSV 다운로드 기능
                csv = target_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("결과 CSV 저장", data=csv, file_name="search_results.csv")
            else:
                st.warning("검색 결과가 없습니다.")

    else:
        st.info("검색어를 입력하시면 사이트별 통합 결과를 확인하실 수 있습니다.")
        preview = run_query("SELECT * FROM env_data LIMIT 10")
        if not preview.empty:
            st.dataframe(preview[selected_display_cols], width='stretch')

except Exception as e:
    st.error(f"시스템 오류 발생: {e}")

st.divider()
st.caption("© 2026 환경부 데이터 검색 대시보드")
