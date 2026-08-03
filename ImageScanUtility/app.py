import io
import json
import base64

import streamlit as st
from PIL import Image
from openai import OpenAI
from prompt import PROMPT

st.set_page_config(
    page_title="AI Cheque Extraction Platform",
    page_icon="🏦",
    layout="wide",
)

st.markdown(
    """
<style>
.block-container{
    padding-top:1rem;
    max-width:1500px;
}

.main-title{
    background: linear-gradient(135deg,#0F172A,#1E293B);
    padding:25px;
    border-radius:15px;
    color:white;
    margin-bottom:20px;
}

.info-card{
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px;
    padding: 14px;
    margin-bottom: 12px;
    backdrop-filter: blur(10px);
}

.info-label{
    font-size: 12px;
    color: #9CA3AF;
    font-weight: 600;
    margin-bottom: 4px;
}

.info-value{
    font-size: 18px;
    font-weight: 700;
    color: inherit;
    word-wrap: break-word;
}

.result-panel{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 15px;
    padding: 20px;
}

.stButton>button{
    width:100%;
    height:50px;
    border-radius:10px;
    font-weight:600;
    font-size:16px;
}
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource
def get_client():
    return OpenAI(
        base_url="https://router.huggingface.co/v1", api_key=st.secrets["HF_TOKEN"]
    )


client = get_client()


MODEL_MAPPING = {
    "Qwen 32B": "Qwen/Qwen3-VL-32B-Instruct:featherless-ai",
    "Qwen 72B": "Qwen/Qwen2.5-VL-72B-Instruct:ovhcloud",
    "Gemma 27B": "google/gemma-3-27b-it:featherless-ai",
}


def info_card(title, value):
    if value is None:
        value = "-"

    st.markdown(
        f"""
        <div class="info-card">
            <div class="info-label">{title}</div>
            <div class="info-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def image_to_base64_png(uploaded_file):
    uploaded_file.seek(0)
    with Image.open(uploaded_file) as img:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def clean_json_response(raw_text):
    cleaned = raw_text.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]

    if cleaned.startswith("```"):
        cleaned = cleaned[3:]

    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]

    return cleaned.strip()


def process_cheque(uploaded_file, model_name):
    image_b64 = image_to_base64_png(uploaded_file)

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            }
        ],
        temperature=0,
    )

    raw_response = response.choices[0].message.content
    cleaned = clean_json_response(raw_response)

    try:
        return json.loads(cleaned)
    except Exception:
        return {
            "error": "Invalid JSON Returned",
            "raw_response": raw_response,
        }


st.markdown(
    """
<div class="main-title">
<h1>🏦 AI Cheque Extraction Platform</h1>
<p>Enterprise-grade Vision AI for Automated Cheque Information Extraction</p>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("⚙ Processing Settings")

    selected_model_label = st.selectbox(
        "Select Vision Model",
        list(MODEL_MAPPING.keys()),
        index=1,
    )

    selected_model = MODEL_MAPPING[selected_model_label]

    uploaded_file = st.file_uploader(
        "Upload Cheque Image", type=["jpg", "jpeg", "png", "bmp", "tiff", "tif"]
    )

    extract_button = st.button("🚀 Extract Information", use_container_width=True)

if uploaded_file:
    image = Image.open(uploaded_file)

    left, right = st.columns([1, 1])

    with left:
        st.subheader("🖼 Cheque Preview")
        st.image(image, use_container_width=True)

    if extract_button:
        with st.spinner("Extracting cheque information..."):
            uploaded_file.seek(0)
            result = process_cheque(uploaded_file, selected_model)

        st.success(f"Extraction completed successfully using {selected_model_label}")

        with right:
            st.markdown(
                """
            <div class="result-panel">
                <h3 style="margin-top:0;">📋 Extracted Information</h3>
            </div>
            """,
                unsafe_allow_html=True,
            )

            st.write("")

            if "error" not in result:
                c1, c2 = st.columns(2)

                with c1:
                    info_card("🏦 Bank Name", result.get("bank_name"))
                    info_card("📄 Cheque Number", result.get("cheque_number"))
                    info_card("🏢 MICR Code", result.get("micr_code"))
                    info_card("🏛 IFSC Code", result.get("ifsc_code"))
                    info_card("📅 Date", result.get("date"))

                    info_card(
                        "✍ Signature",
                        "Present" if result.get("signature_present") else "Not Found",
                    )

                with c2:
                    info_card("💳 Account Number", result.get("account_number"))
                    info_card("👤 Payee Name", result.get("payee_name"))
                    info_card("💰 Amount (Numeric)", result.get("amount_numeric"))
                    info_card("📝 Amount (Words)", result.get("amount_words"))
                    info_card("👨‍💼 Signature Name", result.get("signature_name"))

                    amount_match = result.get("is_amount_matching")

                    if amount_match is True:
                        st.success("✅ Amount in Words matches Amount in Figures")
                    elif amount_match is False:
                        st.error("❌ Amount in Words DOES NOT match Amount in Figures")
                    else:
                        st.warning("⚠ Unable to Validate Amount")

            else:
                st.error(result["error"])
                st.code(result.get("raw_response", ""))

        st.divider()

        st.subheader("📊 Extraction Details")

        tab1, tab2 = st.tabs(["Business View", "Raw JSON"])

        with tab1:
            if "error" not in result:
                rows = [
                    {"Field": "Bank Name", "Value": result.get("bank_name")},
                    {"Field": "Cheque Number", "Value": result.get("cheque_number")},
                    {"Field": "MICR Code", "Value": result.get("micr_code")},
                    {"Field": "Account Number", "Value": result.get("account_number")},
                    {"Field": "IFSC Code", "Value": result.get("ifsc_code")},
                    {"Field": "Date", "Value": result.get("date")},
                    {"Field": "Payee Name", "Value": result.get("payee_name")},
                    {
                        "Field": "Amount (Numeric)",
                        "Value": result.get("amount_numeric"),
                    },
                    {"Field": "Amount (Words)", "Value": result.get("amount_words")},
                    {
                        "Field": "Amount Validation",
                        "Value": (
                            "MATCHED"
                            if result.get("is_amount_matching") is True
                            else "NOT MATCHED"
                            if result.get("is_amount_matching") is False
                            else "UNKNOWN"
                        ),
                    },
                    {
                        "Field": "Signature Present",
                        "Value": ("YES" if result.get("signature_present") else "NO"),
                    },
                    {"Field": "Signature Name", "Value": result.get("signature_name")},
                ]

                st.dataframe(rows, use_container_width=True, hide_index=True)

        with tab2:
            st.json(result)

        st.download_button(
            "⬇ Download JSON",
            data=json.dumps(result, indent=4),
            file_name="cheque_extraction.json",
            mime="application/json",
            use_container_width=True,
        )

else:
    st.info("Upload a cheque image from the sidebar and click Extract Information.")
