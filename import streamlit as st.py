import streamlit as st
import pandas as pd
import gdown
import os

FILE_ID = '1PawLusQwMxxPqf9KKi3jx0dwfz2qrseU'
TMP_FILE = 'data_cache.csv'

@st.cache_data(show_spinner=False)
def load_data_optimized(file_id):
    url = f'https://drive.google.com/uc?id={file_id}'
    if not os.path.exists(TMP_FILE):
        gdown.download(url, TMP_FILE, quiet=False, fuzzy=True)
    
    # [최적화 1] 필요한 컬럼만 지정하거나, 데이터 타입을 압축해서 읽기
    # 우선 모든 컬럼을 읽되, 메모리 효율을 위해 'low_memory=True'로 설정
    try:
        # 엔진을 c 또는 pyarrow로 설정하여 속도와 메모리 최적화
        df = pd.read_csv(TMP_FILE, engine='c', low_memory=True)
    except:
        df = pd.read_csv(TMP_FILE, engine='c', low_memory=True, encoding='cp949')
    
    # [최적화 2] 텍스트 데이터의 메모리 점유율을 줄이기 위해 타입 변환
    # 객체(Object) 타입을 카테고리나 문자열로 최적화
    return df

st.set_page_config(page_title="환경부 검색기", layout="wide")

# 세션 상태를 이용해 데이터 로드 (메모리 중복 점유 방지)
if 'df' not in st.session_state:
    try:
        st.session_state.df = load_data_optimized(FILE_ID)
    except Exception as e:
        st.error(f"서버 메모리 부족 또는 파일 오류: {e}")
        st.stop()

df = st.session_state.df

st.title("🌊 환경부 데이터 조회 시스템")

# --- 검색창 최적화 ---
# 50만 줄을 '전체 열' 검색하면 서버가 터집니다. 
# 사용자가 검색할 컬럼을 하나 선택하게 하는 것이 가장 안전합니다.
columns = ["전체"] + list(df.columns)
search_col = st.selectbox("검색할 항목(컬럼)을 선택하세요", columns)
search_query = st.text_input("검색어 입력 후 Enter")

if search_query:
    with st.spinner('검색 중...'):
        if search_col == "전체":
            # 전체 검색은 메모리를 많이 쓰므로 주의가 필요합니다.
            mask = df.astype(str).apply(lambda x: x.str.contains(search_query, case=False, na=False)).any(axis=1)
        else:
            # 특정 컬럼 검색 (매우 빠르고 안전함)
            mask = df[search_col].astype(str).str.contains(search_query, case=False, na=False)
        
        result = df[mask]
        st.write(f"🔍 결과: {len(result):,}건")
        st.dataframe(result, width='stretch')
else:
    st.info("검색어를 입력해주세요. (상위 50건 미리보기)")
    st.dataframe(df.head(50), width='stretch')
