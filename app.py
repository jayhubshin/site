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

def extract_base_address(address):
    if not address: return ""
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

# --- 페이지 설정 ---
st.set_page_config(page_title="환경부 고속 검색 시스템", layout="wide")

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
    
    # --- 상단 헤더 및 설정 레이아웃 (3:7 비율 적용) ---
    header_col, config_col = st.columns([3, 7])

    with header_col:
        st.title("🚀 환경부 데이터 통합 검색기")
        st.markdown("환경부 데이터를 실시간으로 조회합니다.")

    with config_col:
        with st.expander("⚙️ 보기 방식 및 표시 컬럼 설정", expanded=True):
            # 설정 내부에서도 가로로 배치하여 공간 활용
            mode_col, col_filter_col = st.columns([1, 2])
            with mode_col:
                view_mode = st.radio("보기 방식", ["상세 데이터", "사이트별 통합"], horizontal=False)
            with col_filter_col:
                default_cols = [
                    '충전소명', '도로명주소', '상세위치', '충전소구분상세', 
                    '운영기관명', '운영기관명칭', '충전용량', '충전기등록일시', 
                    '설치년', '설치년도', '설치월'
                ]
                actual_default = [c for c in default_cols if c in all_cols]
                selected_display_cols = st.multiselect("표시할 컬럼을 선택하세요", options=all_cols, default=actual_default)

    st.divider()
    
    # --- 검색 영역 ---
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력", placeholder="아파트 이름이나 주소를 입력하세요 (예: 산들3단지)")

    if search_query:
        with st.spinner('유관 데이터 포함 검색 중...'):
            if search_target == "전체":
                where_clauses = [f"\"{col}\" LIKE '%{search_query}%'" for col in all_cols]
                sql_primary = f"SELECT 도로명주소 FROM env_data WHERE {' OR '.join(where_clauses)} LIMIT 1000"
            else:
                sql_primary = f"SELECT 도로명주소 FROM env_data WHERE \"{search_target}\" LIKE '%{search_query}%' LIMIT 1000"
            
            primary_addresses = run_query(sql_primary)

            if not primary_addresses.empty:
                unique_addresses = primary_addresses['도로명주소'].dropna().unique().tolist()
                address_list_str = "', '".join([addr.replace("'", "''") for addr in unique_addresses])
                sql_final = f"SELECT * FROM env_data WHERE 도로명주소 IN ('{address_list_str}')"
                
                df_result = run_query(sql_final)

                if view_mode == "사이트별 통합":
                    if '도로명주소' in df_result.columns and '충전소명' in df_result.columns:
                        df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                        
                        group_cols = ['통합주소']
                        if '운영기관명칭' in df_result.columns:
                            group_cols.append('운영기관명칭')
                        
                        site_names = df_result.groupby(group_cols)['충전소명'].first().reset_index()
                        site_names.rename(columns={'충전소명': '사이트명'}, inplace=True)
                        df_result = pd.merge(df_result, site_names, on=group_cols, how='left')
                        
                        df_result['충전기대수'] = 1
                        final_group_keys = ['통합주소', '사이트명']
                        if '운영기관명칭' in df_result.columns:
                            final_group_keys.append('운영기관명칭')
                            
                        agg_rules = {col: 'first' for col in selected_display_cols if col not in final_group_keys}
                        agg_rules['충전기대수'] = 'count'
                        
                        final_df = df_result.groupby(final_group_keys).agg(agg_rules).reset_index()
                        
                        show_cols = ['사이트명', '충전기대수']
                        extra_cols = [c for c in selected_display_cols if c not in show_cols and c in final_df.columns]
                        final_show = show_cols + extra_cols
                        
                        target_df = final_df[final_show]
                        target_df.index = range(1, len(target_df) + 1)
                        
                        st.subheader(f"🔍 통합 검색 결과: {len(target_df):,}개 사이트")
                        st.dataframe(target_df, use_container_width=True)
                    else:
                        st.warning("필요한 컬럼이 없어 통합할 수 없습니다.")
                        df_result.index = range(1, len(df_result) + 1)
                        st.dataframe(df_result[selected_display_cols], use_container_width=True)
                        target_df = df_result
                else:
                    df_result.index = range(1, len(df_result) + 1)
                    st.subheader(f"🔍 상세 검색 결과: {len(df_result):,}건")
                    st.dataframe(df_result[selected_display_cols], use_container_width=True)
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
            st.dataframe(preview[selected_display_cols] if selected_display_cols else preview, use_container_width=True)

except Exception as e:
    st.error(f"시스템 오류 발생: {e}")

st.divider()
st.caption("© 2026 환경부 데이터 검색 대시보드")
