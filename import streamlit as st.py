import streamlit as st
import pandas as pd
import gdown
import os

# --- 설정 및 데이터 로드 함수 ---
FILE_ID = '1PawLusQwMxxPqf9KKi3jx0dwfz2qrseU'

@st.cache_data(show_spinner=False)
def load_data_from_drive(file_id):
    url = f'https://drive.google.com/uc?id={file_id}'
    output = 'data_cache.csv'
    
    # 파일이 로컬에 없을 때만 다운로드 (서버 자원 절약)
    if not os.path.exists(output):
        gdown.download(url, output, quiet=False)
    
    # 50만 줄 대응: 메모리 효율을 위해 low_memory=False 설정
    # 만약 한글이 깨진다면 encoding='cp949' 또는 'euc-kr'을 추가하세요.
    df = pd.read_csv(output, low_memory=False)
    return df

# --- UI 구성 ---
st.set_page_config(page_title="환경부 데이터 검색기", layout="wide")

st.title("🌊 환경부 데이터 조회 대시보드")
st.markdown(f"**구글 드라이브 원본 파일 ID:** `{FILE_ID}`")

try:
    # 데이터 로딩 표시
    with st.status("데이터 준비 중...", expanded=True) as status:
        st.write("구글 드라이브 연결 확인...")
        df = load_data_from_drive(FILE_ID)
        st.write("데이터 구조 분석 및 색인 중...")
        status.update(label="데이터 로드 완료!", state="complete", expanded=False)

    # 상단 요약 대시보드
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("총 레코드 수", f"{len(df):,} 건")
    m2.metric("컬럼(항목) 수", f"{len(df.columns)} 개")
    m3.metric("데이터 상태", "정상 (실시간)")

    # --- 검색 영역 ---
    st.subheader("🔍 실시간 검색")
    
    # 검색 방식 선택
    search_col = st.selectbox("검색할 컬럼을 선택하세요 (전체 검색은 '전체' 선택)", ["전체"] + list(df.columns))
    search_query = st.text_input("검색어를 입력하고 엔터를 누르세요", placeholder="예: 시설명, 주소 등")

    if search_query:
        # 50만 줄 고속 검색 로직
        if search_col == "전체":
            # 모든 열을 문자열로 변환하여 검색 (조금 느릴 수 있음)
            mask = df.astype(str).apply(lambda x: x.str.contains(search_query, case=False, na=False)).any(axis=1)
        else:
            # 특정 열만 타겟팅하여 검색 (훨씬 빠름)
            mask = df[search_col].astype(str).str.contains(search_query, case=False, na=False)
        
        filtered_df = df[mask]
        
        st.write(f"결과: **{len(filtered_df):,}** 건이 검색되었습니다.")
        st.dataframe(filtered_df, use_container_width=True)
        
        # 검색 결과 다운로드 버튼
        csv = filtered_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("결과 CSV로 내보내기", data=csv, file_name="search_result.csv", mime="text/csv")
    
    else:
        st.info("검색어를 입력하시면 결과를 확인할 수 있습니다. (현재는 상위 50건 표시)")
        st.dataframe(df.head(50), use_container_width=True)

except Exception as e:
    st.error(f"데이터를 불러오는 중 오류가 발생했습니다.")
    st.expander("상세 에러 보기").write(e)
    st.info("팁: 구글 드라이브 파일의 공유 설정이 '링크가 있는 모든 사용자'로 되어 있는지 확인해 보세요.")

# ---
