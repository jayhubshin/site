import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re

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

# 주소에서 "번지"까지만 추출 (정밀 통합용)
def extract_base_address(address):
    if not address: return ""
    # "~~로 123", "~~길 123-4" 형식까지만 추출 (상세주소 제거)
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

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
    
    # 기본 표시 컬럼 설정 (운영기관명칭 포함)
    default_cols = ['충전소명', '도로명주소', '상세위치', '충전소구분상세', '운영기관명', '운영기관명칭', '충전용량', '충전기등록일시', '설치년', '설치월']
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
        search_query = st.text_input("검색어 입력", placeholder="아파트 이름이나 주소를 입력하세요")

    if search_query:
        with st.spinner('데이터 분석 및 주소 정밀 통합 중...'):
            if search_target == "전체":
                where_clauses = [f"\"{col}\" LIKE '%{search_query}%'" for col in all_cols]
                sql = f"SELECT * FROM env_data WHERE {' OR '.join(where_clauses)} LIMIT 3000"
            else:
                sql = f"SELECT * FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 3000"
            
            df_result = run_query(sql)

            if not df_result.empty:
                if view_mode == "통합 데이터 (사이트별)":
                    if '도로명주소' in df_result.columns and '충전소명' in df_result.columns:
                        # 1. 번지수 기준 통합주소 생성
                        df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                        
                        # 2. 사이트명 매핑 (통합주소 기준 첫번째 이름)
                        site_map = df_result.groupby('통합주소')['충전소명'].first().to_dict()
                        df_result['사이트명'] = df_result['통합주소'].map(site_map)
                        
                        # 3. 집계
                        df_result['충전기대수'] = 1
                        group_key = ['통합주소', '사이트명']
                        agg_rules = {col: 'first' for col in selected_display_cols if col not in group_key}
                        agg_rules['충전기대수'] = 'count'
                        
                        final_df = df_result.groupby(group_key).agg(agg_rules).reset_index()
                        
                        # 4. 출력 컬럼 정리
                        show_cols = ['사이트명', '충전기대수']
                        extra_cols = [c for c in selected_display_cols if c not in show_cols and c in final_df.columns]
                        final_show = show_cols + extra_cols
                        
                        st.subheader(f"🔍 통합 검색 결과: {len(final_df):,}개 사이트")
                        st.dataframe(final_df[final_show], width='stretch')
                        target_df = final_df[final_show]
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
        st.info("검색어를 입력하시면 결과를 확인할 수 있습니다.")
        preview = run_query("SELECT * FROM env_data LIMIT 10")
        if not preview.empty:
            st.dataframe(preview[selected_display_cols] if selected_display_cols else preview, width='stretch')

except Exception as e:
    st.error(f"시스템 오류 발생: {e}")

st.divider()
st.caption("© 2026 환경부 데이터 검색 대시보드")
