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
    
    # 1. 보기 방식 및 컬럼 설정
    st.subheader("⚙️ 화면 설정")
    view_mode = st.radio("보기 방식 선택", ["상세 데이터 (충전기별)", "통합 데이터 (주소/아파트별)"], horizontal=True)
    
    default_cols = ['충전소명', '도로명주소', '상세위치', '충전소구분상세', '운영기관명', '충전용량', '충전기등록일시', '설치년', '설치월']
    actual_default = [c for c in default_cols if c in all_cols]
    
    selected_display_cols = st.multiselect(
        "표시할 컬럼을 선택하세요", 
        options=all_cols, 
        default=actual_default
    )
    
    st.divider()
    
    # 2. 검색 설정
    col1, col2 = st.columns([1, 2])
    with col1:
        search_target = st.selectbox("검색할 항목(컬럼) 선택", ["전체"] + all_cols)
    with col2:
        search_query = st.text_input("검색어 입력", placeholder="아파트 이름이나 주소를 입력하고 Enter")

    # --- 데이터 로드 로직 ---
    if search_query:
        with st.spinner('데이터 분석 중...'):
            if search_target == "전체":
                where_clauses = [f"\"{col}\" LIKE '%{search_query}%'" for col in all_cols]
                sql = f"SELECT * FROM env_data WHERE {' OR '.join(where_clauses)} LIMIT 2000"
            else:
                sql = f"SELECT * FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 2000"
            
            result = run_query(sql)
            
            if view_mode == "통합 데이터 (주소/아파트별)":
                # 주소와 충전소명을 기준으로 그룹화
                # 충전용량은 숫자형으로 변환 후 합산, 나머지는 대표값(첫번째) 표시
                if '충전용량' in result.columns:
                    result['충전용량'] = pd.to_numeric(result['충전용량'], errors='coerce').fillna(0)
                
                group_cols = ['도로명주소', '충전소명']
                # 실제 데이터에 컬럼이 있는지 확인
                group_cols = [c for c in group_cols if c in result.columns]
                
                if group_cols:
                    agg_dict = {col: 'first' for col in result.columns if col not in group_cols}
                    # 충전기 대수 세기 및 용량 합계 추가
                    agg_dict['충전기대수'] = 'count'
                    if '충전용량' in result.columns:
                        agg_dict['총충전용량(합계)'] = 'sum'
                    
                    # 그룹화 실행
                    # 임시로 count용 컬럼 생성
                    result['충전기대수'] = 1
                    if '충전용량' in result.columns:
                        result['총충전용량(합계)'] = result['충전용량']
                        
                    result = result.groupby(group_cols).agg({
                        **{c: 'first' for c in selected_display_cols if c not in group_cols},
                        '충전기대수': 'count',
                        '총충전용량(합계)': 'sum' if '충전용량' in result.columns else 'count'
                    }).reset_index()
                    
                    # 표시 컬럼에 '충전기대수' 추가
                    if '충전기대수' not in selected_display_cols:
                        selected_display_cols = ['충전기대수'] + selected_display_cols

            st.subheader(f"🔍 결과: {len(result):,}건")
            display_df = result[selected_display_cols] if selected_display_cols else result
            st.dataframe(display_df, width='stretch')
            
            csv = display_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("결과를 CSV로 저장", data=csv, file_name="search_results.csv")

    else:
        st.info("검색어를 입력하시면 결과를 확인할 수 있습니다.")
        preview_df = run_query("SELECT * FROM env_data LIMIT 10")
        st.dataframe(preview_df[selected_display_cols] if selected_display_cols else preview_df, width='stretch')

except Exception as e:
    st.error(f"시스템 오류가 발생했습니다: {e}")
    st.info("데이터의 컬럼명(도로명주소, 충전소명 등)이 실제와 일치하는지 확인해주세요.")

st.divider()
st.caption("© 2026 환경부 데이터 검색 대시보드")
