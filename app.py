import os
import sys
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(base_dir, '.env'))
sys.path.append(base_dir)

from src.core.verifier import verify_prescription
from src.core.audit_log import log_decision, get_recent_logs

SAMPLE_PRESCRIPTIONS = {
    "Safe Routine Rx (Low Risk)": {
        "patient": "Male, 45, No known allergies. PMH: Hypertension.",
        "text": "Rx: Amlodipine 5mg OD x 30 days.\nDiagnosis: Essential Hypertension."
    },
    "Severe Interaction (High Risk)": {
        "patient": "Female, 68, PMH: Atrial Fibrillation. Currently taking Warfarin 5mg OD.",
        "text": "Rx: Ciprofloxacin 500mg BID x 7 days.\nDiagnosis: UTI."
    },
    "Pregnancy Contraindication (High Risk)": {
        "patient": "Female, 28, Pregnant (2nd Trimester).",
        "text": "Rx: Lisinopril 10mg OD x 30 days.\nDiagnosis: Gestational Hypertension."
    },
    "Duplicate Therapy / Dose Warning (Medium Risk)": {
        "patient": "Male, 55, PMH: High Cholesterol.",
        "text": "Rx: Atorvastatin 80mg OD.\nRx: Simvastatin 40mg OD."
    },
    "Custom Input": {
        "patient": "",
        "text": ""
    }
}

def main():
    st.set_page_config(
        page_title="UAE Rx Verification System",
        page_icon="💊",
        layout="wide"
    )

    st.markdown("""
    <style>
    .high-risk { background-color: #ffe6e6; padding: 15px; border-left: 5px solid #ff4b4b; border-radius: 5px; margin-bottom: 20px;}
    .med-risk { background-color: #fff4e6; padding: 15px; border-left: 5px solid #ffa500; border-radius: 5px; margin-bottom: 20px;}
    .low-risk { background-color: #e6ffe6; padding: 15px; border-left: 5px solid #00cc44; border-radius: 5px; margin-bottom: 20px;}
    </style>
    """, unsafe_allow_html=True)

    st.title("💊 Prescription Verification System (RAG + Human-in-Loop)")
    st.markdown("*AI-Assisted Drug Safety & UAE MOH Compliance Checker*")
    st.divider()

    # Sidebar
    with st.sidebar:
        st.header("👨‍⚕️ Pharmacist Profile")
        pharmacist_id = st.text_input("Pharmacist ID", value="PHARM-UAE-001")
        st.divider()
        st.header("📊 System Stats")
        logs = get_recent_logs(100)
        st.metric("Prescriptions Checked", len(logs))
        high_risk_prevented = sum(1 for l in logs if l['ai_risk_level'] == 'HIGH' and l['pharmacist_decision'] == 'REJECTED')
        st.metric("High Risk Errors Prevented", high_risk_prevented)

    # Main content area tabs
    tab_verify, tab_audit = st.tabs(["📝 Verify Prescription", "📋 Audit Log"])

    with tab_verify:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("1. Input Details")
            preset = st.selectbox("Load Sample Case:", list(SAMPLE_PRESCRIPTIONS.keys()))
            
            patient_info = st.text_area("Patient Information (Age, Gender, Allergies, PMH):", 
                                      value=SAMPLE_PRESCRIPTIONS[preset]["patient"], height=100)
            
            prescription_text = st.text_area("Prescription Text (e.g., from OCR or EMR):", 
                                           value=SAMPLE_PRESCRIPTIONS[preset]["text"], height=150)
            
            check_btn = st.button("🔍 Run AI Safety Check", type="primary", use_container_width=True)

        with col2:
            st.subheader("2. AI Safety Analysis")
            
            if "ai_result" not in st.session_state:
                st.info("👈 Enter details and click 'Run AI Safety Check' to begin.")
            
            if check_btn:
                if not prescription_text.strip():
                    st.error("Please enter prescription text.")
                else:
                    with st.spinner("Querying UAE Drug Knowledge Base and analyzing safety..."):
                        result = verify_prescription(prescription_text, patient_info)
                        st.session_state.ai_result = result
                        st.session_state.current_rx = prescription_text
                        st.session_state.current_pt = patient_info

            if "ai_result" in st.session_state:
                res = st.session_state.ai_result
                
                # Display Risk Banner
                if res.get("risk_level") == "HIGH":
                    st.markdown('<div class="high-risk"><h3>🚨 HIGH RISK DETECTED</h3>This prescription contains severe contraindications or interactions. Do not dispense without doctor consultation.</div>', unsafe_allow_html=True)
                elif res.get("risk_level") == "MEDIUM":
                    st.markdown('<div class="med-risk"><h3>⚠️ MEDIUM RISK</h3>Caution required. Please review warnings carefully before dispensing.</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="low-risk"><h3>✅ LOW RISK</h3>No major safety issues detected based on provided context.</div>', unsafe_allow_html=True)

                st.markdown(f"**Identified Drugs:** `{', '.join(res.get('identified_drugs', []))}`")
                
                with st.expander("View Detailed Findings", expanded=True):
                    if res.get("interactions_found") and res["interactions_found"] != ["None"]:
                        st.error("**Interactions:**\n" + "\n".join(f"- {i}" for i in res["interactions_found"]))
                    if res.get("contraindications_found") and res["contraindications_found"] != ["None"]:
                        st.error("**Contraindications:**\n" + "\n".join(f"- {c}" for c in res["contraindications_found"]))
                    if res.get("dosage_warnings") and res["dosage_warnings"] != ["None"]:
                        st.warning("**Dosage Notes:**\n" + "\n".join(f"- {d}" for d in res["dosage_warnings"]))
                        
                    st.info(f"**AI Recommendation:** {res.get('pharmacist_recommendation')}")

                st.divider()
                st.subheader("3. Human-in-Loop Decision")
                
                notes = st.text_area("Pharmacist Notes (Required if Rejecting/Modifying):", key="pharm_notes")
                
                d_col1, d_col2, d_col3 = st.columns(3)
                
                # Create a unique ID for the prescription check
                rx_id = f"RX-{len(logs)+1000}"
                
                flags_summary = []
                if res.get("interactions_found"): flags_summary.extend(res["interactions_found"])
                if res.get("contraindications_found"): flags_summary.extend(res["contraindications_found"])
                flags_str = " | ".join(flags_summary) if flags_summary else "None"

                def submit_decision(decision):
                    if decision != "APPROVED" and not st.session_state.pharm_notes:
                        st.toast("Notes required when rejecting or escalating!", icon="⚠️")
                        return
                        
                    log_decision(
                        prescription_id=rx_id,
                        patient_name=st.session_state.current_pt[:50],
                        drugs=", ".join(res.get("identified_drugs", [])),
                        ai_risk_level=res.get("risk_level", "UNKNOWN"),
                        ai_flags=flags_str,
                        pharmacist_id=pharmacist_id,
                        pharmacist_decision=decision,
                        pharmacist_notes=st.session_state.pharm_notes
                    )
                    st.success(f"Decision '{decision}' logged successfully for {rx_id}.")
                    del st.session_state.ai_result

                if d_col1.button("✅ APPROVE & DISPENSE", type="primary", use_container_width=True, disabled=(res.get("risk_level") == "HIGH")):
                    submit_decision("APPROVED")
                
                if d_col2.button("📞 CALL DOCTOR", use_container_width=True):
                    submit_decision("ESCALATED_TO_DOCTOR")
                    
                if d_col3.button("❌ REJECT", use_container_width=True):
                    submit_decision("REJECTED")

    with tab_audit:
        st.subheader("HIPAA-Ready Audit Trail")
        logs = get_recent_logs(50)
        if logs:
            df = pd.DataFrame(logs)
            df = df[["timestamp", "prescription_id", "pharmacist_id", "ai_risk_level", "pharmacist_decision", "pharmacist_notes", "drugs"]]
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No audit logs found yet.")


if __name__ == "__main__":
    main()
