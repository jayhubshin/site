import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import os
import re
import pydeck as pdk

# --- 1. 파일 및 DB 설정 ---
DB_NAME = 'data.db'
ZIP_NAME = 'data.db.zip'

@st.cache_resource
def prepare_db():
    if not os.path.exists(DB_NAME):
        if os.path.exists(ZIP_NAME):
            with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
                zip_ref.extractall('./')
    
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_memos (
                site_key TEXT PRIMARY KEY, 
                memo TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    return True

def run_query(query):
    with sqlite3.connect(DB_NAME, check_same_thread=False) as conn:
        return pd.read_sql_query(query, conn)

def save_memo(site_key, memo_text):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT OR REPLACE INTO site_memos (site_key, memo) VALUES (?, ?)", (site_key, memo_text))

def extract_base_address(address):
    if not address: return ""
    match = re.search(r'(.+[로|길]\s*\d+(-\d+)?)', str(address))
    return match.group(1).strip() if match else str(address).strip()

def parse_lat_lon(df):
    if '위치정보' in df.columns:
        coords = df['위치정보'].astype(str).str.replace(' ', '').str.split(',', expand=True)
        if coords.shape[1] >= 2:
            df['lat'] = pd.to_numeric(coords[0], errors='coerce')
            df['lon'] = pd.to_numeric(coords[1], errors='coerce')
            df = df.dropna(subset=['lat', 'lon'])
            df = df[(df['lat'] > 32) & (df['lat'] < 40) & (df['lon'] > 124) & (df['lon'] < 132)]
    return df

# --- 스타일링 함수 추가 ---
def style_by_operator(row):
    """운영기관명칭에 따라 행 배경색을 결정합니다."""
    # 에버온 포함 시 옅은 파랑, 아니면 옅은 빨강
    is_everon = '에버온' in str(row.get('운영기관명칭', ''))
    bg_color = '#E3F2FD' if is_everon else '#FFEBEE'
    return [f'background-color: {bg_color}'] * len(row)

# --- 2. 앱 설정 ---
st.set_page_config(page_title="환경부 통합 검색 & 통계 시스템 v1.2.5", layout="wide")

st.markdown("""
    <style>
    /* 1. 상단 공백(여백) 제거 */
    .block-container {
        padding-top: 1.5rem !important;    /* 기본 약 6rem에서 1rem으로 대폭 축소 */
        padding-bottom: 0rem !important;
        padding-left: 3rem !important;
        padding-right: 3rem !important;
    }
    

    /* 1. multiselect 전체 배경 및 선택된 항목(Chip) 디자인 */
    span[data-baseweb="tag"] {
        background-color: #E3F2FD !important; /* 부드러운 파란색 배경 */
        border: 1px solid #2196F3 !important; /* 파란색 테두리 */
        border-radius: 4px !important;
        padding-right: 5px !important;
    }
    
    /* 2. 칩 내부 글자 색상 (진한 파란색으로 가독성 확보) */
    span[data-baseweb="tag"] span {
        color: #0D47A1 !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
    }
    
    /* 3. 삭제 아이콘(X) 디자인 */
    span[data-baseweb="tag"] svg {
        fill: #1976D2 !important;
        transition: transform 0.2s;
    }
    
    span[data-baseweb="tag"] svg:hover {
        fill: #D32F2F !important; /* 마우스 올리면 빨간색으로 변경 */
        transform: scale(1.2);
    }

    /* 4. '표시 컬럼 수정' 라벨 폰트 조정 */
    div[data-testid="stMarkdownContainer"] p {
        font-weight: bold !important;
        color: #333 !important;
    }
    
    /* 5. 데이터프레임 내 사이트명 강조 (선택 사항) */
    .stDataFrame [data-testid="stTable"] td:first-child {
        background-color: #F0F7FF !important;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

prepare_db()
@st.cache_data
def get_column_names():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT * FROM env_data LIMIT 1")
        return [description[0] for description in cursor.description]

# --- 3. 메인 로직 ---
try:
    all_cols = get_column_names()
    st.title("🚀 환경부 통합 검색 & 통계 시스템 v1.2.5")
    
    s_col1, s_col2 = st.columns([1, 3])
    with s_col1:
        search_target = st.selectbox("검색 항목", ["전체"] + all_cols)
    with s_col2:
        search_query = st.text_input("검색어 입력 (예: '파인에비뉴 에버온')")

    if search_query:
        with st.spinner('데이터 분석 중...'):
            keywords = search_query.split()
            include_words = [w for w in keywords if not w.startswith('!')]
            exclude_words = [w[1:] for w in keywords if w.startswith('!') and len(w) > 1]

            base_word = include_words[0] if include_words else ""
            sql = f"SELECT * FROM env_data WHERE (도로명주소 LIKE '%{base_word}%' OR 충전소명 LIKE '%{base_word}%' OR 운영기관명칭 LIKE '%{base_word}%')"
            df_raw = run_query(sql)

            def advanced_filter(row):
                row_str = " ".join(row.astype(str).values)
                return all(w in row_str for w in include_words) and not any(w in row_str for w in exclude_words)

            df_result = df_raw[df_raw.apply(advanced_filter, axis=1)].copy()

            if not df_result.empty:
                df_result['충전기대수'] = 1
                df_result['통합주소'] = df_result['도로명주소'].apply(extract_base_address)
                
                group_keys = ['통합주소', '운영기관명칭']
                site_map = df_result.groupby(group_keys)['충전소명'].first().reset_index()
                site_map.rename(columns={'충전소명': '사이트명'}, inplace=True)
                df_result = pd.merge(df_result, site_map, on=group_keys, how='left')

                agg_dict = {col: 'first' for col in df_result.columns if col not in group_keys + ['사이트명', '충전기대수']}
                agg_dict['충전기대수'] = 'count'
                target_df_site = df_result.groupby(group_keys + ['사이트명']).agg(agg_dict).reset_index()

                # 메모 데이터 결합
                memos_df = run_query("SELECT site_key, memo FROM site_memos")
                target_df_site['site_key'] = target_df_site['사이트명'] + "_" + target_df_site['통합주소']
                target_df_site = pd.merge(target_df_site, memos_df, on='site_key', how='left')
                target_df_site['현장비고'] = target_df_site['memo'].fillna("")

                m1, m2, m3 = st.columns([2, 2, 3])
                m1.metric("🏠 검색된 사이트 수", f"{len(target_df_site):,} 개")
                m2.metric("🔌 검색된 총 충전기 수", f"{len(df_result):,} 대")
                with m3:
                    view_mode = st.radio("📋 목록 보기 방식", ["사이트별", "충전기별"], horizontal=True)

                final_display_df = target_df_site if view_mode == "사이트별" else df_result
                tab1, tab2, tab3 = st.tabs(["📊 검색결과 목록", "📍 지도 분포", "🏢 운영기관별 통계"])

                with tab1:
                    requested_cols = ['사이트명', '현장비고', '충전기대수', '도로명주소', '운영기관명칭', '설치년도', '충전기등록일시']
                    display_options = ['사이트명', '현장비고', '충전기대수'] + [c for c in all_cols if c not in ['사이트명', '충전기대수']]
                    actual_default = [c for c in requested_cols if c in display_options or c == '현장비고']
                    selected_cols = st.multiselect("📋 표시 컬럼 수정:", options=display_options, default=actual_default)

                    final_df = final_display_df[[c for c in selected_cols if c in final_display_df.columns]].copy()
                    
                    # 스타일 적용
                    styled_final_df = final_df.style.apply(style_by_operator, axis=1)

                    # 행 선택 기능
                    event = st.dataframe(
                        styled_final_df, use_container_width=True, hide_index=True,
                        on_select="rerun", selection_mode="single-row"
                    )

                    selected_site_from_table = None
                    if len(event.selection.rows) > 0:
                        selected_row_idx = event.selection.rows[0]
                        selected_site_from_table = final_df.iloc[selected_row_idx]['사이트명']

                    st.divider()
                    st.subheader("📝 현장 점검 내용 기록")
                    
                    site_list = ["선택 안 함"] + target_df_site['사이트명'].tolist()
                    default_idx = site_list.index(selected_site_from_table) if selected_site_from_table in site_list else 0
                    
                    c1, c2 = st.columns([1, 2])
                    with c1:
                        target_site = st.selectbox("기록할 사이트", options=site_list, index=default_idx)
                    
                    with c2:
                        if target_site != "선택 안 함":
                            site_data = target_df_site[target_df_site['사이트명'] == target_site]
                            current_memo = site_data['현장비고'].values[0]
                            memo_text = st.text_area("내용 입력 (기록 후 저장 버튼 클릭)", value=current_memo, height=100)
                            if st.button("✅ 메모 저장"):
                                s_key = site_data['site_key'].values[0]
                                save_memo(s_key, memo_text)
                                st.success(f"'{target_site}' 저장 완료!")
                                st.rerun()
                        else:
                            current_memo = "💡 목록에서 행을 클릭하면 저장 버튼이 활성화됩니다."
                            memo_text = st.text_area("내용 입력 (기록 후 저장 버튼 클릭)", value=current_memo, height=100, disabled=True)

                with tab2:
                    map_df = parse_lat_lon(target_df_site.copy())
                    if not map_df.empty:
                        map_df['count_text'] = map_df['충전기대수'].astype(str)
                        map_df['color'] = map_df['운영기관명칭'].apply(lambda x: [0, 102, 204, 140] if '에버온' in str(x) else [220, 30, 30, 140])
                        map_df['radius'] = 10 + (map_df['충전기대수'] * 10)
                        
                        s_layer = pdk.Layer(
                            "ScatterplotLayer", map_df, get_position='[lon, lat]',
                            get_color='color', get_radius='radius',
                            radius_min_pixels=10, radius_max_pixels=40,
                            pickable=True, stroked=True, get_line_color=[255, 255, 255]
                        )
                        t_layer = pdk.Layer(
                            "TextLayer", map_df, get_position='[lon, lat]', get_text='count_text',
                            get_color=[255, 255, 255], get_size=35, size_units="'meters'",
                            size_min_pixels=10, size_max_pixels=35,
                            get_alignment_baseline="'center'", get_text_anchor="'middle'",
                            font_weight=900, outline_width=2, outline_color=[0, 0, 0]
                        )
                        st.pydeck_chart(pdk.Deck(
                            map_style="light",
                            initial_view_state=pdk.ViewState(latitude=map_df['lat'].median(), longitude=map_df['lon'].median(), zoom=14),
                            layers=[s_layer, t_layer],
                            tooltip={"html": "<b>{사이트명}</b><br/>{운영기관명칭}<br/>비고: {현장비고}"}
                        ))

                with tab3:
                    st.subheader("🏢 운영기관별 요약")
                    op_sum = df_result.groupby('운영기관명칭').agg(사이트수=('사이트명', 'nunique'), 총충전기수=('충전기대수', 'sum')).reset_index().sort_values('총충전기수', ascending=False)
                    # 통계 테이블에도 색상 적용
                    styled_op_sum = op_sum.style.apply(style_by_operator, axis=1)
                    st.dataframe(styled_op_sum, use_container_width=True, hide_index=True)
            else:
                st.warning("결과가 없습니다.")
    else:
        st.info("검색어를 입력하세요.")
except Exception as e:
    st.error(f"오류 발생: {e}")
