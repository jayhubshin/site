import streamlit as st
import pandas as pd
import gdown
import os

# --- 설정 ---
FILE_ID = '1PawLusQwMxxPqf9KKi3jx0dwfz2qrseU'
TMP_FILE = 'data_cache.csv'

@st.cache_data(show_spinner=False)
def load_data(file_id):
    url = f'https://drive.google.com/uc?id={file_id}'
    
    # 1. 파일 다운로드 (gdown 활용)
    if not os.path.exists(TMP_FILE):
        gdown.download(url, TMP_FILE, quiet=False, fuzzy=True)
    
    # 2. 메모리 최적화 읽기
    try:
        # 50만 줄 로드 시 메모리 점유를 줄이기 위해 low_memory=False 사용
        df = pd.read_csv(TMP_FILE, low_memory=False)
    except:
        df = pd.read_csv(TMP_FILE, low_memory=False, encoding='cp949')
        
    return df

st.set_page_config(page_title="환경부 데이터 검색기", layout="wide")

st.title("🌊 환경부 데이터 조회 시스템 (2026 최신판)")

# 데이터 로딩 세션 관리
if 'df' not in st.session_state:
    try:
        with st.spinner('대용량 데이터를 분석 중입니다...'):
            st.session_state.df = load_data(FILE_ID)
        st.success("데이터 로드 완료!")
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        st.stop()

df = st.session_state.df

# --- 검색 인터페이스 ---
search_query = st.text_input("검색어를 입력하세요", placeholder="시설명, 지역, 내용 등 입력 후 Enter")

if search_query:
    with st.spinner('50만 행 탐색 중...'):
        # 성능 최적화: vectorize된 str.contains 활용
        # 모든 열을 검사하되 문자열 타입인 열만 골라서 검색 속도 향상
        mask = df.astype(str).apply(lambda x: x.str.contains(search_query, case=False, na=False)).any(axis=1)
        result = df[mask]
        
    st.write(f"🔍 검색 결과: **{len(result):,}** 건")
    
    # 2026년 Streamlit 표준: width='stretch' 사용
    st.dataframe(result, width='stretch')
    
    # 결과 다운로드 기능
    csv = result.to_csv(index=False).encode('utf-8-sig')
    st.download_button("결과 저장 (CSV)", data=csv, file_name="search_result.csv")
else:
    st.info("검색어를 입력하시면 결과를 확인할 수 있습니다.")
    # 초기 화면 50건 미리보기 (최신 표준 반영)
    st.dataframe(df.head(50), width='stretch')
