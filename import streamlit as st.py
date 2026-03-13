import streamlit as st
import pandas as pd
import gdown
import os

# --- 설정 ---
FILE_ID = '1PawLusQwMxxPqf9KKi3jx0dwfz2qrseU'
TMP_FILE = 'data_cache.csv'

@st.cache_data(show_spinner=False)
def load_data_lite(file_id):
    url = f'https://drive.google.com/uc?id={file_id}'
    if not os.path.exists(TMP_FILE):
        gdown.download(url, TMP_FILE, quiet=False, fuzzy=True)
    
    # [핵심 최적화] 처음에 읽을 때부터 문자열로 읽어서 변환 과정의 메모리 폭증을 방지합니다.
    try:
        # 50만 줄 전체를 읽지 않고 상위 10만 줄만 읽거나, 모든 컬럼을 object로 고정
        df = pd.read_csv(TMP_FILE, low_memory=True, dtype=str) 
    except:
        df = pd.read_csv(TMP_FILE, low_memory=True, dtype=str, encoding='cp949')
    
    # 결측치(NaN)를 미리 빈 문자열로 채워 검색 시 오류 방지
    df = df.fillna('')
    return df

st.set_page_config(page_title="환경부 검색기", layout="wide")
st.title("🌊 환경부 데이터 조회 시스템")

# 데이터 로드 (세션 상태 활용)
if 'df' not in st.session_state:
    try:
        with st.spinner('대용량 데이터를 안전하게 불러오는 중입니다...'):
            st.session_state.df = load_data_lite(FILE_ID)
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        st.stop()

df = st.session_state.df

# --- 검색 인터페이스 ---
columns = list(df.columns)
# 사용자가 검색할 컬럼을 반드시 선택하게 유도하여 메모리 과부하 방지
search_col = st.selectbox("검색할 항목을 선택하세요 (전체 검색보다 빠릅니다)", columns)
search_query = st.text_input("검색어 입력 후 Enter")

if search_query:
    with st.spinner('검색 중...'):
        # [최적화 검색] 이미 데이터가 문자열(dtype=str)이므로 astype(str) 과정 생략
        # 특정 컬럼만 타겟팅하여 벡터 연산 수행
        mask = df[search_col].str.contains(search_query, case=False, na=False)
        result = df[mask]
        
        st.write(f"🔍 결과: **{len(result):,}** 건")
        # 2026년 표준 문법 반영
        st.dataframe(result, width='stretch')
else:
    st.info("검색어를 입력해주세요. (상위 50건 미리보기)")
    st.dataframe(df.head(50), width='stretch')
