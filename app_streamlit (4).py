import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime

CFG = "config/"
PATH_STEPS = CFG + "steps.csv"
PATH_OPTIONS = CFG + "options.csv"
PATH_SUBOPTIONS = CFG + "suboptions.csv"
PATH_ANSWERS = CFG + "answers.csv"
PATH_CIRC = CFG + "circulars.csv"
PATH_RULES = CFG + "rules.csv"

@st.cache_data
def load_csv(path, cols=None):
    try:
        df = pd.read_csv(path)
        if cols:
            for c in cols:
                if c not in df.columns: df[c] = ""
        return df
    except Exception:
        return pd.DataFrame(columns=cols or [])

steps_df      = load_csv(PATH_STEPS, ["StepID","StepLabel","Help","Order","Active"])
options_df    = load_csv(PATH_OPTIONS, ["OptionID","StepID","OptionLabel","Order","Active"])
subopts_df    = load_csv(PATH_SUBOPTIONS, ["SubOptionID","OptionID","SubOptionLabel","Order","Active"])
answers_df    = load_csv(PATH_ANSWERS, ["StepID","OptionID","SubOptionID","AnswerText","NeedsCircular","CircularID","Active"])
circ_df       = load_csv(PATH_CIRC, ["CircularID","Title","LinkOrFile","EffectiveFrom","Active"])
rules_df      = load_csv(PATH_RULES, ["RuleID","ConditionExpr","OutcomeText","CircularID","Severity","Active"])

st.set_page_config(page_title="Tender Checklist", page_icon="🧾", layout="wide")
st.title("Tender Checklist & Scrutiny (Streamlit)")

mode = st.sidebar.radio("Mode", [
    "Checklist", "Scrutiny", "Summary",
    "Admin - Steps/Options", "Admin - Answers", "Admin - Circulars", "Admin - Rules"
])

# Helpers

def active(df):
    return df[df["Active"].str.lower()=="yes"] if "Active" in df.columns else df

def get_options(step_id):
    return active(options_df[options_df["StepID"]==step_id]).sort_values("Order")

def get_suboptions(option_id):
    return active(subopts_df[subopts_df["OptionID"]==option_id]).sort_values("Order")

def find_answer(step_id, option_id, subopt_id=None):
    q = active(answers_df[(answers_df["StepID"]==step_id) & (answers_df["OptionID"]==option_id)])
    if subopt_id:
        q = q[q["SubOptionID"]==subopt_id]
    else:
        q = q[(q["SubOptionID"].isna()) | (q["SubOptionID"]=="")]
    return q.iloc[0] if len(q) else None

def circ_by_id(cid):
    r = active(circ_df[circ_df["CircularID"]==cid])
    return r.iloc[0] if len(r) else None

def save_csv(df, path):
    df.to_csv(path, index=False)
    st.success(f"Saved → {path}")

# Checklist
if mode=="Checklist":
    st.subheader("Checklist")
    selections = {}
    cols = st.columns(2)

    for _, step in active(steps_df).sort_values("Order").iterrows():
        col = cols[0] if step["Order"]%2==1 else cols[1]
        with col:
            st.markdown(f"**{step['StepLabel']}**")
            st.caption(step["Help"])
            opts = get_options(step["StepID"]) 
            sel_opt = st.selectbox(
                f"Select: {step['StepLabel']}",
                ["-- select --"] + opts["OptionLabel"].tolist(),
                key=f"opt_{step['StepID']}"
            )
            selections[step["StepLabel"]] = sel_opt

            sub_sel = ""
            if sel_opt != "-- select --":
                opt_row = opts[opts["OptionLabel"]==sel_opt].iloc[0]
                subs = get_suboptions(opt_row["OptionID"])
                if len(subs):
                    sub_sel = st.selectbox(
                        f"Sub option for {sel_opt}",
                        ["-- select --"] + subs["SubOptionLabel"].tolist(),
                        key=f"sub_{step['StepID']}"
                    )
                    selections[f"{step['StepLabel']} (sub)"] = sub_sel

            if sel_opt != "-- select --":
                ans = None
                if sub_sel and sub_sel != "-- select --":
                    so = get_suboptions(opt_row["OptionID"]).query("SubOptionLabel == @sub_sel").iloc[0]
                    ans = find_answer(step["StepID"], opt_row["OptionID"], so["SubOptionID"])
                else:
                    ans = find_answer(step["StepID"], opt_row["OptionID"], None)

                if ans is not None and str(ans["AnswerText"]).strip():
                    st.info(f"Standard answer: {ans['AnswerText']}")
                    if str(ans["NeedsCircular"]).lower()=="yes" and str(ans["CircularID"]).strip():
                        circ = circ_by_id(ans["CircularID"])
                        if circ is not None:
                            st.markdown(f"**Circular:** [{circ['Title']}]({circ['LinkOrFile']})")
                else:
                    st.warning("No standard answer found. Please refer the relevant circular (if any).")
                    fallback = active(answers_df[(answers_df["StepID"]==step["StepID"]) & (answers_df["OptionID"]==opt_row["OptionID"])])
                    if len(fallback):
                        cid = fallback.iloc[0]["CircularID"]
                        circ = circ_by_id(cid)
                        if circ is not None:
                            st.markdown(f"**Circular:** [{circ['Title']}]({circ['LinkOrFile']})")

    st.session_state["selections"] = selections

# Scrutiny
elif mode=="Scrutiny":
    st.subheader("Scrutiny (rule-based)")
    selections = st.session_state.get("selections", {})
    ctx = {}
    key_map = {
        "Tender value":"TenderValue",
        "Portal":"Portal",
        "Type of work":"TypeOfWork",
        "Standard template":"StandardTemplate",
        "Floor price":"FloorPrice",
        "Reverse auction":"ReverseAuction",
        "Category":"Category",
        "Special tender":"SpecialTender"
    }
    for lbl, val in selections.items():
        for step_lbl, key in key_map.items():
            if step_lbl.lower() in lbl.lower():
                ctx[key] = val
    st.write("Current context:", ctx)

    reports = []
    for _, r in active(rules_df).iterrows():
        try:
            cond = r["ConditionExpr"]
            ok = eval(cond, {}, ctx)  # restricted eval
            if ok:
                row = {"RuleID": r["RuleID"], "Severity": r["Severity"], "Advice": r["OutcomeText"]}
                if str(r["CircularID"]).strip():
                    c = circ_by_id(r["CircularID"])
                    if c is not None:
                        row["Circular"] = f"{c['Title']} ({c['LinkOrFile']})"
                reports.append(row)
        except Exception as e:
            reports.append({"RuleID": r["RuleID"], "Severity":"Warn", "Advice":f"Rule error: {e}"})

    if reports:
        for rep in reports:
            sev = rep.get("Severity","Info")
            if sev.lower()=="warn": st.warning(rep["Advice"])
            else: st.info(rep["Advice"])
            if rep.get("Circular"): st.markdown(f"See: {rep['Circular']}")
    else:
        st.success("No advice or flags. (Rules did not trigger)")

# Summary
elif mode=="Summary":
    st.subheader("Summary")
    selections = st.session_state.get("selections", {})
    rows = []
    for lbl, val in selections.items():
        rows.append({"Field": lbl, "Selected": val})
    df_out = pd.DataFrame(rows)
    st.dataframe(df_out, use_container_width=True)

    def download_excel():
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as w:
            df_out.to_excel(w, index=False, sheet_name="Summary")
        bio.seek(0)
        return bio

    st.download_button("Download Excel Summary", data=download_excel(), file_name=f"Summary_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")

# Admin - Steps/Options
elif mode=="Admin - Steps/Options":
    st.subheader("Admin – Steps & Options")
    st.caption("Use 'Order' to control display sequence. Active=Yes to show.")

    steps_edit = st.data_editor(steps_df, num_rows="dynamic", use_container_width=True)
    if st.button("Save steps"):
        save_csv(steps_edit, PATH_STEPS); steps_df = steps_edit

    st.markdown("---")
    options_edit = st.data_editor(options_df, num_rows="dynamic", use_container_width=True)
    if st.button("Save options"):
        save_csv(options_edit, PATH_OPTIONS); options_df = options_edit

    st.markdown("---")
    subopts_edit = st.data_editor(subopts_df, num_rows="dynamic", use_container_width=True)
    if st.button("Save suboptions"):
        save_csv(subopts_edit, PATH_SUBOPTIONS); subopts_df = subopts_edit

# Admin - Answers
elif mode=="Admin - Answers":
    st.subheader("Admin – Standard Answers")
    st.caption("Map (Step, Option, SubOption?) to a standard answer. Tick NeedsCircular and choose CircularID if required.")
    ans_edit = st.data_editor(answers_df, num_rows="dynamic", use_container_width=True)
    if st.button("Save answers"):
        save_csv(ans_edit, PATH_ANSWERS); answers_df = ans_edit

# Admin - Circulars
elif mode=="Admin - Circulars":
    st.subheader("Admin – Circulars Library")
    circ_edit = st.data_editor(circ_df, num_rows="dynamic", use_container_width=True)
    if st.button("Save circulars"):
        save_csv(circ_edit, PATH_CIRC); circ_df = circ_edit

# Admin - Rules
elif mode=="Admin - Rules":
    st.subheader("Admin – Rules")
    st.caption("ConditionExpr evaluates over keys like TenderValue, Portal, TypeOfWork, StandardTemplate, FloorPrice, ReverseAuction, Category, SpecialTender.")
    rules_edit = st.data_editor(rules_df, num_rows="dynamic", use_container_width=True)
    if st.button("Save rules"):
        save_csv(rules_edit, PATH_RULES); rules_df = rules_edit
