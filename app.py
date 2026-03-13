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
    
    # 1. 컬럼 표시 필터 (멀티셀렉트)
    default_cols = ['충전소명', '도로명주소', '상세위치', '충전소구분상세', '운영기관명', '충전용량', '충전기등록일시', '설치년', '설치월']
    # 실제 데이터에 해당 컬럼이 있는지 확인 후 기본값 설정
    actual_default = [c for c in default_cols if c in all_cols]
    
    st.subheader("⚙️ 보기 설정")
    selected_display_cols = st.multiselect(
        "표시할 컬럼을 선택하세요", 
        options=all_cols, 
        default=actual_default
    )
    
    st.divider()
    
    # 2. 검색 설정
    col1, col2 = st.columns([1, 2])
    with col1:
        # "전체" 옵션 추가
        search_target = st.selectbox("검색할 항목(컬럼) 선택", ["전체"] + all_cols)
    with col2:
        search_query = st.text_input("검색어 입력", placeholder="검색어를 입력하고 Enter를 눌러주세요")

    # --- 검색 로직 ---
    if search_query:
        with st.spinner('데이터베이스 탐색 중...'):
            if search_target == "전체":
                # 모든 컬럼에 대해 OR 조건 생성 (성능을 위해 상위 1000건 제한)
                where_clauses = [f"\"{col}\" LIKE '%{search_query}%'" for col in all_cols]
                sql = f"SELECT * FROM env_data WHERE {' OR '.join(where_clauses)} LIMIT 1000"
            else:
                sql = f"SELECT * FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 1000"
            
            result = run_query(sql)
            
        st.subheader(f"🔍 검색 결과: {len(result):,}건")
        
        # 필터링된 컬럼만 출력 (사용자가 선택한 컬럼이 있을 때만)
        display_df = result[selected_display_cols] if selected_display_cols else result
        
        st.dataframe(display_df, width='stretch')
        
        # 다운로드 버튼
        csv = display_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("결과를 CSV로 저장", data=csv, file_name="search_results.csv", mime="text/csv")

    else:
        st.info("검색어를 입력하시면 결과를 확인할 수 있습니다.")
        st.write("📋 데이터 미리보기 (상위 10건)")
        preview_df = run_query("SELECT * FROM env_data LIMIT 10")
        # 미리보기에서도 필터 적용
        display_preview = preview_df[selected_display_cols] if selected_display_cols else preview_df
        st.dataframe(display_preview, width='stretch')

except Exception as e:
    st.error(f"시스템 오류가 발생했습니다: {e}")
    st.info("데이터베이스의 컬럼명과 코드에 설정된 기본 컬럼명이 일치하는지 확인해주세요.")

st.divider()
st.caption("© 2026 환경부 데이터 검색 대시보드 | Powered by SQLite & Streamlit")
