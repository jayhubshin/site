import streamlit as st
import pandas as pd

# 1. 구글 드라이브에서 CSV 읽기 함수 (캐싱 처리로 속도 최적화)
@st.cache_data
def load_data(file_id):
    # 구글 드라이브 다운로드 URL 포맷
    url = "https://drive.google.com/file/d/1PawLusQwMxxPqf9KKi3jx0dwfz2qrseU/view?usp=drive_link"
    df = pd.read_csv(url)
    return df
# 파일 ID 입력 (본인의 파일 ID로 교체하세요)
GOOGLE_DRIVE_FILE_ID = '여러분의_파일_ID_입력'

st.title("📂 데이터 검색 서비스")
st.write("50만 줄의 데이터를 실시간으로 검색합니다.")

# 데이터 로딩
with st.spinner('데이터를 불러오는 중입니다...'):
    data = load_data(GOOGLE_DRIVE_FILE_ID)

# 2. 검색창 구현
search_term = st.text_input("검색어를 입력하세요 (예: 제품명, 지역 등)")

# 3. 검색 로직 (전체 컬럼에서 해당 단어가 포함된 행 찾기)
if search_term:
    # 문자열 데이터에서 검색어 포함 여부 확인 (대소문자 무시)
    mask = data.astype(str).apply(lambda x: x.str.contains(search_term, case=False)).any(axis=1)
    results = data[mask]
    
    st.write(f"🔍 검색 결과: {len(results)}건")
    st.dataframe(results)  # 결과 표 출력
else:
    st.write("상단 검색창에 검색어를 입력해 주세요.")

    st.dataframe(data.head(100)) # 초기 화면에는 상위 100개만 표시
