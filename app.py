# GitHub PR Code Review Agent
# Stage 1: Receive webhook
# Stage 2: Fetch the code diff from GitHub
# Stage 3: Send diff to Claude, get review back
# Stage 4: Post the review as a comment on the PR

from flask import Flask, request, jsonify
import requests
import anthropic

app = Flask(__name__)
import os
from dotenv import load_dotenv
load_dotenv()

GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# Edit this to change what Claude looks for in reviews
# No coding needed — just rewrite this in plain English
REVIEW_PROMPT = """
You are an expert code reviewer. Review the following code diff and provide feedback on:

1. Bugs or potential errors
2. Security issues (hardcoded secrets, SQL injection, etc.)
3. Performance problems
4. Bad practices or code style issues
5. Anything that looks unclear or hard to maintain

Format your response as a clear, concise code review comment.
Use bullet points. Be specific about line numbers or variable names where possible.
If the code looks good, say so briefly and mention what's done well.
Keep the review under 300 words.
"""


def fetch_pr_diff(repo_name, pr_number):
    """Fetch the code diff for a pull request."""
    url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/files"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"  GitHub API error: {response.status_code} {response.text}")
        return None

    files = response.json()

    full_diff = ""
    for file in files:
        filename = file["filename"]
        patch    = file.get("patch", "")

        if patch:
            full_diff += f"\n--- File: {filename} ---\n"
            full_diff += patch
            full_diff += "\n"

    return full_diff


def get_claude_review(diff):
    """Send the diff to Claude and get a code review back."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print("Sending diff to Claude...")

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=REVIEW_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Please review this code diff:\n\n{diff}"
            }
        ]
    )

    review = message.content[0].text
    print(f"Got review from Claude ({len(review)} chars)")
    return review


def post_pr_comment(repo_name, pr_number, review):
    """
    Post the review as a comment on the GitHub PR.

    GitHub's API for PR comments is just:
    POST /repos/{repo}/issues/{pr_number}/comments
    with a JSON body containing the comment text.

    PRs and Issues share the same comment system on GitHub,
    which is why the URL says 'issues' even for a PR.
    """
    url = f"https://api.github.com/repos/{repo_name}/issues/{pr_number}/comments"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Wrap the review in a nice header so it's clear it's AI-generated
    comment_body = f"## 🤖 AI Code Review\n\n{review}\n\n---\n*Review generated automatically by Claude*"

    payload = {"body": comment_body}

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 201:
        comment_url = response.json().get("html_url")
        print(f"✓ Comment posted: {comment_url}")
        return True
    else:
        print(f"  Failed to post comment: {response.status_code} {response.text}")
        return False


@app.route("/webhook", methods=["POST"])
def webhook():
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    print(f"\nReceived event: {event_type}")

    data = request.json

    if event_type != "pull_request":
        print("Not a PR event, ignoring.")
        return jsonify({"status": "ignored"}), 200

    action = data.get("action")
    print(f"PR action: {action}")

    if action not in ("opened", "synchronize"):
        print(f"Action '{action}' doesn't need a review, ignoring.")
        return jsonify({"status": "ignored"}), 200

    pr_number = data["pull_request"]["number"]
    pr_title  = data["pull_request"]["title"]
    repo_name = data["repository"]["full_name"]

    print(f"PR #{pr_number}: '{pr_title}' in {repo_name}")

    # Stage 2: Fetch the diff
    print("Fetching diff from GitHub...")
    diff = fetch_pr_diff(repo_name, pr_number)

    if not diff:
        print("No diff found — PR may have no code changes.")
        return jsonify({"status": "no diff"}), 200

    print(f"Got diff ({len(diff)} chars)")

    # Stage 3: Get Claude's review
    review = get_claude_review(diff)
    print(f"\nCLAUDE'S REVIEW:\n{review}\n")

    # Stage 4: Post it to GitHub
    print("Posting review to GitHub...")
    post_pr_comment(repo_name, pr_number, review)

    return jsonify({"status": "done"}), 200


if __name__ == "__main__":
    app.run(port=5000, debug=True)