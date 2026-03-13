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
    
    default_cols = [
        '충전소명', '도로명주소', '상세위치', '충전소구분상세', 
        '운영기관명', '운영기관명칭', '충전용량', '충전기등록일시', 
        '설치년', '설치년도', '설치월'
    ]
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
        search_query = st.text_input("검색어 입력", placeholder="아파트 이름이나 주소를 입력하세요 (예: 산들3단지)")

    if search_query:
        with st.spinner('유관 데이터 포함 검색 중...'):
            # 1. 1차 검색: 검색어에 해당하는 데이터 찾기
            if search_target == "전체":
                where_clauses = [f"\"{col}\" LIKE '%{search_query}%'" for col in all_cols]
                sql_primary = f"SELECT 도로명주소 FROM env_data WHERE {' OR '.join(where_clauses)} LIMIT 1000"
            else:
                sql_primary = f"SELECT 도로명주소 FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 1000"
            
            primary_addresses = run_query(sql_primary)

            if not primary_addresses.empty:
                # 2. 2차 검색: 검색된 데이터들의 '도로명주소'를 가진 모든 행 가져오기
                unique_addresses = primary_addresses['도로명주소'].dropna().unique().tolist()
                # SQL IN 구문을 위한 처리
                address_list_str = "', '".join([addr.replace("'", "''") for addr in unique_addresses])
                sql_final = f"SELECT * FROM env_data WHERE 도로명주소 IN ('{address_list_str}')"
                
                df_result = run_query(sql_final)

                if view_mode == "통합 데이터 (사이트별)":
                    if '도로명주소' in df_result.columns and '충전소명' in df_result.columns:
                        # 주소 전처리
                        df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                        
                        # [핵심 로직] 주소(번지)와 운영기관명칭이 같아야 같은 사이트로 묶임
                        # 운영기관명칭이 없으면 통합주소로만 묶음
                        group_cols = ['통합주소']
                        if '운영기관명칭' in df_result.columns:
                            group_cols.append('운영기관명칭')
                        
                        # 사이트명 생성 (첫 번째 충전소명 사용)
                        site_names = df_result.groupby(group_cols)['충전소명'].first().reset_index()
                        site_names.rename(columns={'충전소명': '사이트명'}, inplace=True)
                        df_result = pd.merge(df_result, site_names, on=group_cols, how='left')
                        
                        df_result['충전기대수'] = 1
                        
                        # 집계 규칙
                        final_group_keys = ['통합주소', '사이트명']
                        if '운영기관명칭' in df_result.columns:
                            final_group_keys.append('운영기관명칭')
                            
                        agg_rules = {col: 'first' for col in selected_display_cols if col not in final_group_keys}
                        agg_rules['충전기대수'] = 'count'
                        
                        final_df = df_result.groupby(final_group_keys).agg(agg_rules).reset_index()
                        
                        # 컬럼 표시 정리
                        show_cols = ['사이트명', '충전기대수']
                        extra_cols = [c for c in selected_display_cols if c not in show_cols and c in final_df.columns]
                        final_show = show_cols + extra_cols
                        
                        target_df = final_df[final_show]
                        target_df.index = range(1, len(target_df) + 1)
                        
                        st.subheader(f"🔍 통합 검색 결과: {len(target_df):,}개 사이트")
                        st.dataframe(target_df, width='stretch')
                    else:
                        st.warning("필요한 컬럼이 없어 통합할 수 없습니다.")
                        df_result.index = range(1, len(df_result) + 1)
                        st.dataframe(df_result[selected_display_cols], width='stretch')
                        target_df = df_result
                else:
                    df_result.index = range(1, len(df_result) + 1)
                    st.subheader(f"🔍 상세 검색 결과: {len(df_result):,}건")
                    st.dataframe(df_result[selected_display_cols], width='stretch')
                    target_df = df_result

                csv = target_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("결과 CSV 저장", data=csv, file_name="search_results.csv")
            else:
                st.warning("검색 결과가 없습니다.")
    else:
        st.info("검색어를 입력하시면 결과를 확인할 수 있습니다.")
        preview = run_query("SELECT * FROM env_data LIMIT 10")
        if not preview.empty:
            preview.index = range(1, len(preview) + 1)
            st.dataframe(preview[selected_display_cols] if selected_display_cols else preview, width='stretch')

except Exception as e:
    st.error(f"시스템 오류 발생: {e}")

st.divider()
st.caption("© 2026 환경부 데이터 검색 대시보드")
