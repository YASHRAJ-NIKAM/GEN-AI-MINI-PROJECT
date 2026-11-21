import os
import subprocess
import sys
import tempfile
import time
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError

load_dotenv()

st.set_page_config(page_title="Bug Finder & Fixer", page_icon="🛠️", layout="wide")
st.title("🛠️ Bug Finder & Fixer (PS #72)")
st.write(
    "Paste broken code and an error message to get the root cause, fix explanation, "
    "corrected code, and sandbox verification."
)

SAMPLE_TESTS = {
    "Custom Input": {
        "language": "Python",
        "code": "",
        "error": "",
    },
    "1. IndexError (List out of range)": {
        "language": "Python",
        "code": (
            "def average_score(scores):\n"
            "    total = 0\n"
            "    for i in range(len(scores) + 1):\n"
            "        total += scores[i]\n"
            "    return total / len(scores)\n\n"
            "print(average_score([80, 90, 70]))"
        ),
        "error": "IndexError: list index out of range",
    },
    "2. ZeroDivisionError (Empty list)": {
        "language": "Python",
        "code": (
            "def compute_mean(values):\n"
            "    return sum(values) / len(values)\n\n"
            "print(compute_mean([]))"
        ),
        "error": "ZeroDivisionError: division by zero",
    },
    "3. KeyError (Missing dictionary key)": {
        "language": "Python",
        "code": (
            "student = {'name': 'Aarav', 'roll': 72}\n"
            "print('Grade:', student['grade'])"
        ),
        "error": "KeyError: 'grade'",
    },
    "4. TypeError (String + Integer)": {
        "language": "Python",
        "code": (
            "marks = 88\n"
            "message = 'Total Marks: ' + marks\n"
            "print(message)"
        ),
        "error": 'TypeError: can only concatenate str (not "int") to str',
    },
    "5. Logic Bug (Factorial starts at 0)": {
        "language": "Python",
        "code": (
            "def factorial(n):\n"
            "    result = 0\n"
            "    for i in range(1, n + 1):\n"
            "        result *= i\n"
            "    return result\n\n"
            "print(factorial(5))"
        ),
        "error": "",
    },
}

api_key = os.getenv("GEMINI_API_KEY") or st.sidebar.text_input(
    "Gemini API Key", type="password"
)
model_name = st.sidebar.selectbox(
    "Model",
    ["gemini-3.8-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash"],
    index=0,
)
preset = st.sidebar.selectbox("Load Sample Bug Test", list(SAMPLE_TESTS.keys()))

if st.sidebar.button("Fill Sample into Boxes"):
    chosen = SAMPLE_TESTS[preset]
    st.session_state["code_box"] = chosen["code"]
    st.session_state["error_box"] = chosen["error"]
    st.session_state["lang_box"] = chosen["language"]

language = st.sidebar.selectbox(
    "Language",
    ["Python", "Java", "C++", "JavaScript"],
    key="lang_box",
)
run_sandbox = st.sidebar.checkbox("Run fixed Python code in sandbox", value=True)

col1, col2 = st.columns(2)
with col1:
    broken_code = st.text_area(
        "Broken Code",
        height=240,
        key="code_box",
        placeholder="Paste your code here...",
    )
with col2:
    error_msg = st.text_area(
        "Error Message / Traceback",
        height=240,
        key="error_box",
        placeholder="Paste the error here (optional for logic bugs)...",
    )


def run_in_sandbox(code_text: str):
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code_text)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Execution timed out after 5 seconds."
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def extract_code_block(response_text: str) -> str:
    if "```" not in response_text:
        return response_text.strip()
    parts = response_text.split("```")
    if len(parts) >= 2:
        block = parts[1]
        lines = block.splitlines()
        if lines and lines[0].strip().lower() in {
            "python",
            "java",
            "cpp",
            "c++",
            "javascript",
            "js",
        }:
            lines = lines[1:]
        return "\n".join(lines).strip()
    return response_text.strip()


def generate_with_retry(
    client, primary_model: str, prompt: str, max_retries: int = 3
):
    models_to_try = [primary_model]
    for fallback in ["gemini-3.8-flash", "gemini-2.5-flash-lite"]:
        if fallback not in models_to_try:
            models_to_try.append(fallback)

    last_err = None
    for m in models_to_try:
        for attempt in range(1, max_retries + 1):
            try:
                return client.models.generate_content(model=m, contents=prompt), m
            except APIError as e:
                last_err = e
                if e.code in (503, 429, 500) and attempt < max_retries:
                    time.sleep(2**attempt)
                    continue
                break
    raise last_err


if st.button("Find & Fix Bug", type="primary"):
    if not api_key:
        st.error("Please set GEMINI_API_KEY in .env or enter it in the sidebar.")
    elif not broken_code.strip():
        st.warning("Please paste some broken code first.")
    else:
        prompt = f"""
You are a helpful coding assistant and debugger.
Analyze the {language} code and error message below.

Respond using these exact sections:
### Root Cause
(Explain why the bug happens in simple terms)

### Fix Explanation
(Explain what changes fix the bug)

### Corrected Code
(Provide the complete corrected code inside a ```{language.lower()} code block)

Broken Code:
{broken_code}

Error Message:
{error_msg if error_msg.strip() else "No error message provided; check for syntax or logic bugs."}
"""
        try:
            with st.spinner("Analyzing bug and generating fix..."):
                client = genai.Client(api_key=api_key)
                response, used_model = generate_with_retry(client, model_name, prompt)
                output_text = response.text or ""

            st.caption(f"Answered by: `{used_model}`")
            st.markdown("### Diagnosis & Fix")
            st.markdown(output_text)

            if language == "Python" and run_sandbox:
                fixed_code = extract_code_block(output_text)
                st.markdown("### Sandbox Verification (Python)")
                rc, out, err = run_in_sandbox(fixed_code)
                if rc == 0:
                    st.success("Fixed code ran successfully in sandbox!")
                    if out:
                        st.code(out, language="text")
                else:
                    st.error(f"Sandbox finished with exit code {rc}")
                    if err:
                        st.code(err, language="text")
        except Exception as exc:
            st.error(f"Request failed: {exc}")