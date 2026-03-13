import streamlit as st
import sqlite3
import pandas as pd

# DB 연결 함수
def run_query(query):
    conn = sqlite3.connect('data.db', check_same_thread=False)
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

st.set_page_config(page_title="환경부 고속 검색기", layout="wide")
st.title("🚀 환경부 데이터 고속 조회 (SQL 엔진)")

# 검색할 컬럼 리스트 (본인 데이터의 실제 컬럼명으로 수정하세요)
search_target = st.selectbox("검색 항목 선택", ["시설명", "주소", "관리번호"])
search_term = st.text_input("검색어를 입력하세요 (예: 서울)")

if search_term:
    with st.spinner('DB에서 검색 중...'):
        # SQL의 LIKE 문을 사용해 메모리 소모 없이 해당 데이터만 추출
        query = f"SELECT * FROM env_data WHERE {search_target} LIKE '%{search_term}%' LIMIT 500"
        result = run_query(query)
        
    st.write(f"🔍 결과: **{len(result):,}** 건 (최대 500건 표시)")
    st.dataframe(result, width='stretch')
else:
    st.info("검색어를 입력하면 0.1초 만에 결과를 찾습니다.")
