# 🏦 AI Cheque Extraction Platform

Enterprise-grade Vision AI for automated cheque information extraction — powered by state-of-the-art multimodal models via Hugging Face.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-1.x-red) ![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Features

- Upload cheque images (JPG, PNG, BMP, TIFF)
- Extracts key fields: Bank Name, Cheque Number, MICR Code, IFSC Code, Account Number, Payee Name, Date, Amount (numeric & words), Signature
- Validates whether amount in words matches amount in figures
- Choose from multiple Vision AI models (Qwen 32B, Qwen 72B, Gemma 27B)
- Download extracted data as JSON

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- [`uv`](https://github.com/astral-sh/uv) package manager
- A [Hugging Face](https://huggingface.co) account with an API token

---

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/ai-cheque-extraction.git
cd ai-cheque-extraction
```

### 2. Install Dependencies with `uv`

```bash
uv sync
```

This creates a `.venv` virtual environment and installs all dependencies from `pyproject.toml` / `uv.lock`.

To activate the environment manually (optional):

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

---

### 3. Configure Hugging Face Token

This app uses [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers) via Streamlit secrets.

Create a `.streamlit/secrets.toml` file in the project root:

```toml
HF_TOKEN = "hf_your_token_here"
```

> Get your token from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). Make sure it has **read** access.

---

### 4. Run the App

```bash
uv run streamlit run app.py
```

Or if your virtualenv is already activated:

```bash
streamlit run app.py
```

The app will be available at `http://localhost:8501`.

---

## 🤖 Supported Models

| Label | Model ID |
|---|---|
| Qwen 32B | `Qwen/Qwen3-VL-32B-Instruct` via Featherless AI |
| Qwen 72B | `Qwen/Qwen2.5-VL-72B-Instruct` via OVH Cloud |
| Gemma 27B | `google/gemma-3-27b-it` via Featherless AI |

To add a custom model, update the `MODEL_MAPPING` dictionary in `app.py`:

```python
MODEL_MAPPING = {
    "My Custom Model": "org/model-name:provider",
    ...
}
```

---

## 📁 Project Structure

```
.
├── app.py               # Main Streamlit application
├── prompt.py            # Extraction prompt (PROMPT constant)
├── pyproject.toml       # Project dependencies
├── uv.lock              # Locked dependency versions
└── .streamlit/
    └── secrets.toml     # Hugging Face token (not committed)
```

---

## 🔒 Security Note

Never commit `.streamlit/secrets.toml` to version control. Add it to `.gitignore`:

```
.streamlit/secrets.toml
```

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.