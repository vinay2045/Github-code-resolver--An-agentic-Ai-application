import streamlit as st
import os
import re
import json
import base64
import requests
from dotenv import load_dotenv
from phi.agent import Agent
from phi.model.google import Gemini
from phi.storage.agent.sqlite import SqlAgentStorage

# Load environment variables from .env file
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")

# Initialize the Gemini-powered agent
agent = Agent(
    name="GitHub Fixer",
    model=Gemini(id="gemini-1.5-flash", api_key=GEMINI_API_KEY),
    storage=SqlAgentStorage(table_name="agent_history", db_file="agent.db"),
    markdown=True,
    add_history_to_messages=True,
    stream=False  # Disable streaming responses
)

GITHUB_API_URL = "https://api.github.com"

# -----------------------------
# GitHub API Functions
# -----------------------------
def parse_repo_url(repo_url):
    """Extract owner and repo name from GitHub URL."""
    pattern = r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
    match = re.search(pattern, repo_url)
    if match:
        return match.group("owner"), match.group("repo")
    raise ValueError("Invalid GitHub repository URL.")

def get_default_branch(owner, repo):
    """Fetch the default branch of a GitHub repository."""
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("default_branch", "main")
    raise Exception(f"Failed to get repository info: {response.text}")

def get_repo_tree(owner, repo, branch):
    """Retrieve all files in a repository's tree."""
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("tree", [])
    raise Exception(f"Failed to get repository tree: {response.text}")

def get_file_content(owner, repo, path, branch):
    """Get the content of a file from GitHub."""
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    return None, None

def update_file(owner, repo, path, new_content, commit_message, sha, branch):
    """Update a file in a GitHub repository."""
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    encoded_content = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    data = {"message": commit_message, "content": encoded_content, "sha": sha, "branch": branch}
    response = requests.put(url, headers=headers, data=json.dumps(data))
    return response.status_code, response.text

def get_language_from_extension(filename):
    """Map file extensions to syntax highlighting languages."""
    ext_to_lang = {
        ".html": "html", ".css": "css", ".js": "javascript", ".jsx": "javascript",
        ".ts": "typescript", ".tsx": "typescript", ".json": "json", ".md": "markdown",
        ".py": "python", ".java": "java", ".c": "c", ".cpp": "cpp", ".cs": "csharp",
        ".php": "php", ".rb": "ruby", ".go": "go", ".rs": "rust", ".sh": "shell",
        ".yaml": "yaml", ".yml": "yaml"
    }
    return ext_to_lang.get(os.path.splitext(filename)[1].lower(), "plaintext")

# -----------------------------
# AI Processing Functions
# -----------------------------
def fix_code_for_files(files_data, issue_description):
    """
    For each file, send its content with the issue description to the AI agent.
    Instruct the agent to make only the minimal modifications necessary to address the issue,
    and preserve all other parts of the file unchanged.
    Do not rewrite the entire file. Return only the complete updated file content
    exactly as it should appear, with no extra formatting or markdown markers.
    If no changes are needed, return "UNCHANGED".
    """
    fixed_files = {}
    for path, data in files_data.items():
        original = data["original"]
        prompt = (
            f"File: {path}\n"
            f"Issue: {issue_description}\n\n"
            "Instructions:\n"
            "1. Keep the entire original code unchanged except for the minimal modifications needed to address the issue.\n"
            "2. Do not rewrite or reformat the entire file.\n"
            "3. Insert or modify only what is necessary (for example, add an input field and a button in an appropriate location if needed).\n"
            "4. Return only the complete updated file content exactly as it should appear, with no extra formatting, markdown code fences, or commentary.\n"
            "If no change is needed, return 'UNCHANGED'.\n\n"
            "Original File Content:\n"
            f"{original}"
        )
        try:
            response = agent.run(prompt)
            result = response.content.strip()
            # Remove any code fences (e.g., ```css, ```html)
            result = re.sub(r"```[a-zA-Z]*", "", result).strip()
            if result != "UNCHANGED" and result != original:
                fixed_files[path] = {"original": original, "updated": result}
        except Exception as e:
            st.error(f"Error processing {path}: {e}")
    return fixed_files

def show_changes(fixed_files):
    """Display the original and updated code for modified files (vertical layout)."""
    for path, data in fixed_files.items():
        language = get_language_from_extension(path)
        st.markdown(f"### File: `{path}`")
        st.markdown("**Original Code:**")
        st.code(data["original"], language=language)
        st.markdown("**Updated Code:**")
        st.code(data["updated"], language=language)
        st.markdown("---")

# -----------------------------
# Streamlit App UI
# -----------------------------
st.title("GitHub Fixer Streamlit App")
st.write("This app analyzes a GitHub repository and fixes issues using AI. "
         "It applies only minimal changes based on your issue description, leaving all other code intact.")

repo_url = st.text_input("GitHub Repository URL:")
issue_description = st.text_input("Describe the issue to fix:")
commit_message = st.text_input("Commit Message (optional):")

if st.button("Process Repository"):
    if not repo_url or not issue_description:
        st.error("Please provide both the repository URL and issue description.")
    else:
        try:
            owner, repo = parse_repo_url(repo_url)
            branch = get_default_branch(owner, repo)
            st.write(f"**Default branch:** {branch}")
            tree = get_repo_tree(owner, repo, branch)
            allowed_ext = (".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".py", ".java", ".cpp")
            files_data = {}
            for item in tree:
                if item["type"] == "blob" and item["path"].endswith(allowed_ext):
                    content, sha = get_file_content(owner, repo, item["path"], branch)
                    if content:
                        files_data[item["path"]] = {"original": content, "sha": sha}
            if not files_data:
                st.error("No files retrieved. Exiting.")
            else:
                fixed_files = fix_code_for_files(files_data, issue_description)
                if not fixed_files:
                    st.info("Agent did not modify any files.")
                else:
                    st.subheader("Proposed Changes:")
                    show_changes(fixed_files)
                    st.session_state.update({
                        "fixed_files": fixed_files,
                        "files_data": files_data,
                        "owner": owner,
                        "repo": repo,
                        "branch": branch
                    })
                    st.success("Processing complete. Review the proposed changes above.")
        except Exception as e:
            st.error(f"Error: {e}")

if st.button("Commit Changes"):
    if "fixed_files" not in st.session_state:
        st.error("No changes to commit. Process a repository first.")
    elif not commit_message:
        st.error("Please provide a commit message.")
    else:
        fixed_files = st.session_state["fixed_files"]
        files_data = st.session_state["files_data"]
        owner = st.session_state["owner"]
        repo = st.session_state["repo"]
        branch = st.session_state["branch"]
        for path, data in fixed_files.items():
            sha = files_data[path]["sha"]
            update_file(owner, repo, path, data["updated"], commit_message, sha, branch)
        st.success("Changes committed successfully!")
        st.session_state.clear()
        st.info("Please refresh the page to enter new inputs.")
