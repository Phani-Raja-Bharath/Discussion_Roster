from collections import OrderedDict

import streamlit as st

from db.database import (
    connect,
    create_nomination,
    is_integrity_error,
    one,
    rows,
    seed_from_inputs_if_empty,
)
from utils.schedule import display_date, week_details


def count_query(connection, sql):
    result = connection.execute(sql).fetchone()
    return int(result[0]) if result else 0


st.set_page_config(
    page_title="FALL 2026 Discussion Paper Nomination",
    page_icon=":material/description:",
    layout="wide",
)

st.markdown(
    """
<style>
:root { --ucf-gold:#FFC904; --ucf-black:#000; }
.stApp { font-family: Arial, Helvetica, sans-serif; }
[data-testid="stHeader"] { background: #000; }
.ucf-head {background:#000;padding:22px 28px;border-bottom:7px solid #FFC904;border-radius:8px;margin-bottom:22px}
.ucf-head h1,.ucf-head p {color:white;margin:0}
.ucf-head h1 {font-size:2rem}
.week {border-left:7px solid #FFC904;padding:8px 14px;margin-top:18px}
.pending {float:right;font-weight:700;color:#000}
div.stButton > button {background:#FFC904;color:#000;border:1px solid #000;font-weight:700}
[data-testid="stSidebar"], [data-testid="collapsedControl"] {display:none}
</style>
<div class="ucf-head"><h1>FALL 2026 |IDS 5147 | Perspectives in Modeling & Simulation</h1>
<p>Discussion paper Nomination</p></div>
""",
    unsafe_allow_html=True,
)

with st.container(border=True):
    st.markdown(
        "**Instructions:** Browse the papers by week below. Under an available "
        "paper, select your name from the dropdown and click **Nominate**. You "
        "may nominate **one paper total** — once submitted, it's final, so "
        "contact the instructor if you need it changed.\n\n"
        "This link is for students in this class only — please do not share it "
        "with anyone outside the course.\n\n"
        "Questions? Contact **ph380838@ucf.edu**/**soheil.sabri@ucf.edu**."
    )


seed_from_inputs_if_empty()

with connect() as connection:
    paper_count = count_query(connection, "SELECT COUNT(*) FROM papers WHERE active = TRUE")
    student_count = count_query(connection, "SELECT COUNT(*) FROM students WHERE active = TRUE")
    nomination_count = count_query(connection, "SELECT COUNT(*) FROM nominations")

if not paper_count or not student_count:
    st.info(
        "Setup is required. Ask the administrator to open the Admin page and import "
        "the student roster and paper schedule."
    )
    st.stop()

metric_one, metric_two, metric_three = st.columns(3)
metric_one.metric("Available nominations", paper_count - nomination_count)
metric_two.metric("Papers nominated", nomination_count)
metric_three.metric("Total papers", paper_count)

if st.session_state.get("confirmation"):
    confirmation = st.session_state["confirmation"]
    with st.container(border=True):
        st.success("Nomination confirmed.")
        st.markdown(
            f"**{confirmation['week_label']} | {confirmation['date']}**  \n"
            f"{confirmation['topic']}"
        )
        st.write(f"**Paper {confirmation['paper_number']}:** {confirmation['paper_title']}")
        if confirmation["paper_link"]:
            st.link_button("View Paper", confirmation["paper_link"])
        if st.button("Dismiss"):
            del st.session_state["confirmation"]
            st.rerun()

available_students = [
    row[0]
    for row in rows(
        """SELECT name FROM students
           WHERE active = TRUE AND id NOT IN (SELECT student_id FROM nominations)
           ORDER BY name"""
    )
]

paper_rows = rows(
    """SELECT p.id, p.week, p.paper_number, p.paper_title, p.paper_link, s.name
       FROM papers p
       LEFT JOIN nominations n ON n.paper_id = p.id
       LEFT JOIN students s ON s.id = n.student_id
       WHERE p.active = TRUE
       ORDER BY CAST(p.week AS INTEGER), p.paper_number"""
)

weeks = OrderedDict()
for paper_id, week, paper_number, paper_title, paper_link, nominee in paper_rows:
    weeks.setdefault(week, []).append(
        (paper_id, paper_number, paper_title, paper_link, nominee)
    )

if st.session_state.get("pending_nomination"):
    pending_nomination = st.session_state["pending_nomination"]
    with st.container(border=True):
        st.subheader("Confirm Paper Nomination")
        st.write(f"Student: {pending_nomination['student_name']}")
        st.write(f"Week: {pending_nomination['week_label']}")
        if pending_nomination["date"]:
            st.write(f"Date: {pending_nomination['date']}")
        st.write(f"Paper: {pending_nomination['paper_number']}")
        st.write(pending_nomination["paper_title"])
        st.caption("You can nominate only one paper. Please confirm before submitting.")
        cancel, confirm = st.columns(2)
        if cancel.button("Cancel"):
            del st.session_state["pending_nomination"]
            st.rerun()
        if confirm.button("Confirm Nomination", type="primary"):
            student = one(
                "SELECT id FROM students WHERE name = ? AND active = TRUE",
                (pending_nomination["student_name"],),
            )
            if not student:
                st.error("Selected student was not found. Refresh and try again.")
            else:
                if "week" in pending_nomination:
                    paper = one(
                        """SELECT p.id, n.id
                           FROM papers p
                           LEFT JOIN nominations n ON n.paper_id = p.id
                           WHERE p.active = TRUE
                             AND p.week = ?
                             AND p.paper_number = ?""",
                        (
                            pending_nomination["week"],
                            pending_nomination["paper_number"],
                        ),
                    )
                else:
                    paper = one(
                        """SELECT p.id, n.id
                           FROM papers p
                           LEFT JOIN nominations n ON n.paper_id = p.id
                           WHERE p.active = TRUE
                             AND p.id = ?""",
                        (pending_nomination["paper_id"],),
                    )
                if not paper:
                    st.error(
                        f"Paper {pending_nomination['paper_number']} is not available. "
                        "Refresh the page and try again."
                    )
                elif paper[1] is not None:
                    st.error(
                        f"Paper {pending_nomination['paper_number']} has already been nominated. "
                        "Refresh the page and pick another paper."
                    )
                else:
                    try:
                        create_nomination(student[0], paper[0])
                        st.session_state["confirmation"] = pending_nomination
                        del st.session_state["pending_nomination"]
                        st.rerun()
                    except Exception as exc:
                        if is_integrity_error(exc):
                            st.error(
                                "This student or paper has already been nominated. "
                                "Please refresh and try again."
                            )
                        else:
                            st.error(
                                "This paper was just nominated by another student. "
                                "Please refresh and pick another."
                            )

if not available_students:
    st.info("Every student has nominated a paper. Nothing left to sign up for.")

for week, week_papers in weeks.items():
    details = week_details(week)
    pending = sum(1 for paper in week_papers if paper[4] is None)
    st.markdown(
        f"""<div class="week"><h3>{details['week_label']} | {display_date(details['date'])}
<span class="pending">Pending: {pending}</span></h3>
<p>{details['topic']}</p></div>""",
        unsafe_allow_html=True,
    )
    columns = st.columns(4)
    for slot, (paper_id, paper_number, paper_title, paper_link, nominee) in enumerate(week_papers):
        with columns[slot % 4]:
            card_key = f"paper-card-{paper_id}"
            with st.container(border=True, height=500, key=card_key):
                st.markdown(f"**Paper {paper_number}**")

                if nominee:
                    st.markdown("**NOMINATED**")
                    st.caption("Unavailable")
                    st.html(
                        f"<style>.st-key-{card_key} {{"
                        "background-color: #d9f2d9;"
                        "border-color: #2e7d32;"
                        "}</style>"
                    )
                else:
                    choice = st.selectbox(
                        "Student",
                        ["Select your name..."] + available_students,
                        key=f"student-{paper_id}",
                        label_visibility="collapsed",
                    )
                    if st.button(
                        "Nominate",
                        key=f"nominate-{paper_id}",
                        disabled=choice == "Select your name...",
                    ):
                        st.session_state["pending_nomination"] = {
                            "student_name": choice,
                            "paper_id": paper_id,
                            "week": week,
                            "week_label": details["week_label"],
                            "date": display_date(details["date"]),
                            "topic": details["topic"],
                            "paper_number": paper_number,
                            "paper_title": paper_title,
                            "paper_link": paper_link,
                        }
                        st.rerun()

                if paper_link:
                    st.markdown(f"[{paper_title}]({paper_link})")
                else:
                    st.write(paper_title)
