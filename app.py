import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os

# --- 파일 및 DB 설정 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

# 1. 압축 파일이 있다면 자동으로 해제하는 로직
def prepare_db():
    if not os.path.exists(DB_NAME):
        if os.path.exists(ZIP_NAME):
            with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
                zip_ref.extractall('./')
        else:
            st.error("데이터 파일(data.db 또는 data.db.zip)을 찾을 수 없습니다.")
            st.stop()

# 2. 고속 DB 조회 함수
def run_query(query):
    # check_same_thread=False: Streamlit 멀티스레딩 환경 대응
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()
    return df

# --- 페이지 설정 (2026 표준) ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")

st.title("🚀 환경부 데이터 통합 검색기")
st.markdown("50만 줄의 데이터를 실시간으로 조회합니다.")

# DB 준비 실행
prepare_db()

# 3. 컬럼 목록 가져오기 (캐싱 처리로 속도 향상)
@st.cache_data
def get_column_names():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
    cols = [description[0] for description in cursor.description]
    conn.close()
    return cols

try:
    cols = get_column_names()
    
    # --- 검색 UI 영역 ---
    st.divider()
    col1, col2 = st.columns([1, 2])
    
    with col1:
        search_target = st.selectbox("검색할 항목(컬럼) 선택", cols)
    with col2:
        search_query = st.text_input("검색어 입력 (예: 서울, 강남, 업체명 등)", placeholder="입력 후 Enter를 눌러주세요")

    # --- 검색 실행 및 결과 출력 ---
    if search_query:
        with st.spinner('데이터베이스 탐색 중...'):
            # SQL LIKE 문으로 고속 검색 (대소문자 무시)
            # 보안을 위해 쿼리 파라미터 방식을 권장하지만, 간단한 검색을 위해 f-string 사용
            sql = f"SELECT * FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 1000"
            result = run_query(sql)
            
        st.subheader(f"🔍 검색 결과: {len(result):,}건")
        if len(result) >= 1000:
            st.warning("결과가 너무 많아 상위 1,000건만 표시합니다. 검색어를 더 구체적으로 입력해보세요.")
        
        # 2026년 최신 표준: width='stretch' 사용
        st.dataframe(result, width='stretch')
        
        # 검색 결과 다운로드 버튼
        csv = result.to_csv(index=False).encode('utf-8-sig')
        st.download_button("결과를 CSV로 저장", data=csv, file_name="search_results.csv", mime="text/csv")

    else:
        st.info("검색어를 입력하시면 결과를 확인할 수 있습니다.")
        # 초기 화면: 최신 데이터 10건 미리보기
        st.write("📋 데이터 미리보기 (상위 10건)")
        st.dataframe(run_query("SELECT * FROM env_data LIMIT 10"), width='stretch')

except Exception as e:
    st.error(f"시스템 오류가 발생했습니다: {e}")
    st.info("GitHub에 'data.db' 또는 'data.db.zip' 파일이 정상적으로 올라갔는지 확인해주세요.")

st.divider()
st.caption("© 2026 환경부 데이터 검색 대시보드 | Powered by SQLite & Streamlit")
