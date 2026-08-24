import io

import pandas as pd
import streamlit as st

from db.database import (
    INPUTS_DIR,
    PAPERS_JSON,
    SCHEDULE_JSON,
    STUDENTS_JSON,
    admin_password,
    connect,
    dataframe_from_json,
    execute,
    import_papers_df,
    import_students_df,
    paper_schedule_warning,
    read_dataframe,
    read_upload,
    schedule_papers_dataframe,
    students_roster_from_secret,
)
from utils.paper_files import find_paper_file
from utils.schedule import display_date, week_details


def save_input_json(df, path):
    INPUTS_DIR.mkdir(exist_ok=True)
    df.to_json(path, orient="records", indent=2)


st.set_page_config(page_title="Admin | Paper Nomination", layout="wide")
st.markdown(
    """<style>
.stApp{font-family:Arial,Helvetica,sans-serif}
.admin{background:#000;color:white;padding:20px;border-bottom:7px solid #FFC904;border-radius:8px}
div.stButton>button{background:#FFC904;color:#000;font-weight:700}
[data-testid="stSidebar"], [data-testid="collapsedControl"]{display:none}
</style><div class="admin"><h1>UCF | Urban Digital Twin Lab</h1><p>Paper Nomination - Admin Dashboard</p></div>""",
    unsafe_allow_html=True,
)

if "admin_ok" not in st.session_state:
    st.session_state.admin_ok = False
if not st.session_state.admin_ok:
    password = st.text_input("Admin password", type="password")
    if st.button("Sign in"):
        if password == admin_password():
            st.session_state.admin_ok = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()

connect().close()

if admin_password() == "change-me":
    st.warning(
        "ADMIN_PASSWORD is not set — the admin dashboard is using the default "
        "password. Set ADMIN_PASSWORD in .streamlit/secrets.toml (or the app's "
        "Secrets on Streamlit Community Cloud) before sharing this link."
    )

nominations = read_dataframe(
    """SELECT n.id AS "id", s.name AS "Student", p.week AS "Week", p.paper_number AS "Paper #",
              p.paper_title AS "Paper Title", p.paper_link AS "Paper Link",
              n.created_at AS "Submitted"
       FROM nominations n
       JOIN students s ON s.id = n.student_id
       JOIN papers p ON p.id = n.paper_id
       ORDER BY CAST(p.week AS INTEGER), p.paper_number"""
)
missing = read_dataframe(
    """SELECT name AS "Student"
       FROM students
       WHERE active = TRUE
         AND id NOT IN (SELECT student_id FROM nominations)
       ORDER BY name"""
)
paper_status = read_dataframe(
    """SELECT p.id AS "id", p.week AS "Week", p.paper_number AS "Paper #",
              p.paper_title AS "Paper Title", p.paper_link AS "Paper Link",
              CASE WHEN n.id IS NULL THEN 'Available' ELSE 'Nominated' END AS "Status",
              s.name AS "Student"
       FROM papers p
       LEFT JOIN nominations n ON n.paper_id = p.id
       LEFT JOIN students s ON s.id = n.student_id
       WHERE p.active = TRUE
       ORDER BY CAST(p.week AS INTEGER), p.paper_number"""
)
weekly = read_dataframe(
    """SELECT p.week AS "Week", COUNT(n.id) AS "Assigned", COUNT(p.id) AS "Total"
       FROM papers p
       LEFT JOIN nominations n ON n.paper_id = p.id
       WHERE p.active = TRUE
       GROUP BY p.week
       ORDER BY CAST(p.week AS INTEGER)"""
)
if not paper_status.empty:
    paper_status["Week"] = paper_status["Week"].astype(int)
if not weekly.empty:
    weekly["Week"] = weekly["Week"].astype(int)

total_students = len(missing) + len(nominations)
total_papers = len(paper_status)
assigned = len(nominations)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Students", total_students)
col2.metric("Nominated", assigned)
col3.metric("Not nominated", len(missing))
col4.metric("Available nominations", total_papers - assigned)
col5.metric("Papers", total_papers)

warning = paper_schedule_warning()
if warning:
    st.warning(warning)

st.subheader("Weekly status")
if weekly.empty:
    st.info("No paper schedule has been imported yet.")
else:
    for row in weekly.itertuples(index=False):
        st.progress(
            0 if row.Total == 0 else row.Assigned / row.Total,
            text=f"Week {row.Week}: {row.Assigned} / {row.Total}",
        )

st.subheader("Calendar view")
calendar_rows = []
for week, group in paper_status.groupby("Week", sort=True):
    details = week_details(week)
    pending = int((group["Status"] == "Available").sum())
    calendar_row = {
        "Date": display_date(details["date"]),
        "Topic": details["topic"],
        "Paper/Nominee": "",
        "Paper/Nominee2": "",
        "Paper/Nominee3": "",
        "Paper/Nominee4": "",
        "Pending Nomination": pending,
    }
    for slot, (_, paper) in enumerate(group.head(4).iterrows(), start=1):
        nominee = paper["Student"] if pd.notna(paper["Student"]) else "Pending"
        column = "Paper/Nominee" if slot == 1 else f"Paper/Nominee{slot}"
        calendar_row[column] = (
            f"Paper {int(paper['Paper #'])}: {paper['Paper Title']}\nNominee: {nominee}"
        )
    calendar_rows.append(calendar_row)

calendar = pd.DataFrame(calendar_rows)
st.dataframe(calendar, width="stretch", hide_index=True)

st.subheader("Nominations")
st.dataframe(nominations.drop(columns=["id"], errors="ignore"), width="stretch", hide_index=True)

if not nominations.empty:
    options = [
        f"{row['Student']} - Week {row['Week']} - Paper {row['Paper #']}"
        for _, row in nominations.iterrows()
    ]
    remove = st.selectbox("Remove a nomination", ["Select..."] + options)
    if remove != "Select..." and st.button("Remove selected nomination"):
        nomination_id = int(nominations.iloc[options.index(remove)]["id"])
        execute("DELETE FROM nominations WHERE id = ?", (nomination_id,))
        st.rerun()

st.subheader("Students not yet nominated")
st.dataframe(missing, width="stretch", hide_index=True)

st.subheader("Manage data")
students_action, papers_action = st.columns(2)
with students_action:
    secret_roster = None if STUDENTS_JSON.exists() else students_roster_from_secret()
    if STUDENTS_JSON.exists():
        st.caption(f"Found {STUDENTS_JSON.as_posix()}")
        if st.button("Load students from inputs/students.json"):
            try:
                import_students_df(dataframe_from_json(STUDENTS_JSON))
                st.success("Students loaded from JSON.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    elif secret_roster is not None:
        st.caption(
            "inputs/students.json is not on this host, but a STUDENTS_ROSTER "
            "secret is set — this survives reboots/redeploys that the file doesn't."
        )
        if st.button("Load students from STUDENTS_ROSTER secret"):
            try:
                import_students_df(secret_roster)
                st.success("Students loaded from the STUDENTS_ROSTER secret.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    else:
        st.warning("inputs/students.json is missing.")
        students_file = st.file_uploader(
            "Upload student list",
            type=["xlsx", "csv"],
            key="students-upload",
        )
        if st.button("Save and import students", disabled=students_file is None):
            try:
                students_df = read_upload(students_file)
                save_input_json(students_df, STUDENTS_JSON)
                import_students_df(students_df)
                st.success("Saved inputs/students.json and imported students.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        st.caption(
            "Tip: paste the same roster JSON into a STUDENTS_ROSTER secret so it "
            "survives reboots without re-uploading — ask Claude to show you the format."
        )

with papers_action:
    if SCHEDULE_JSON.exists():
        st.caption(f"Found {SCHEDULE_JSON.as_posix()} (dates, topics, and papers together)")
        if st.button("Load papers from inputs/discussion_schedule.json"):
            try:
                import_papers_df(schedule_papers_dataframe(SCHEDULE_JSON))
                st.success("Papers loaded from the discussion schedule.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    elif PAPERS_JSON.exists():
        st.caption(f"Found {PAPERS_JSON.as_posix()}")
        if st.button("Load papers from inputs/papers.json"):
            try:
                import_papers_df(dataframe_from_json(PAPERS_JSON))
                st.success("Papers loaded from JSON.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    else:
        st.warning("inputs/discussion_schedule.json is missing.")
        papers_file = st.file_uploader(
            "Upload paper schedule",
            type=["xlsx", "csv"],
            key="papers-upload",
        )
        if st.button("Save and import papers", disabled=papers_file is None):
            try:
                papers_df = read_upload(papers_file)
                save_input_json(papers_df, PAPERS_JSON)
                import_papers_df(papers_df)
                st.success(
                    "Saved inputs/papers.json and imported papers. Add dates/topics "
                    "by creating inputs/discussion_schedule.json directly."
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

st.subheader("Paper status")
st.dataframe(
    paper_status.drop(columns=["id"], errors="ignore"), width="stretch", hide_index=True
)

st.subheader("Paper files")
st.caption("PDFs live in the Papers/ folder. This cross-checks each paper against it for reference.")
file_rows = []
for _, paper in paper_status.iterrows():
    matched_file = find_paper_file(paper["Paper #"], paper["Paper Title"])
    file_rows.append(
        {
            "Paper #": paper["Paper #"],
            "Paper Title": paper["Paper Title"],
            "Matched file on disk": matched_file.name if matched_file else "",
        }
    )
st.dataframe(pd.DataFrame(file_rows), width="stretch", hide_index=True)

st.subheader("Export")
csv = nominations.drop(columns=["id"], errors="ignore").to_csv(index=False).encode()
st.download_button("Download CSV", csv, "paper_nominations.csv", "text/csv")

buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
    nominations.drop(columns=["id"], errors="ignore").to_excel(
        writer, index=False, sheet_name="Nominations"
    )
    missing.to_excel(writer, index=False, sheet_name="Not Nominated")
    paper_status.drop(columns=["id"], errors="ignore").to_excel(
        writer, index=False, sheet_name="Paper Status"
    )
st.download_button(
    "Download Excel",
    buffer.getvalue(),
    "paper_nominations.xlsx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
