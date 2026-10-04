#!/usr/bin/env python3
"""
gen_github_actions.py — Generate a combined GitHub Actions workflow for all
scheduled IG + LinkedIn posts in a month.

ARCHITECTURE: One cron job per post. At cron time the job:
  1. Checks out the repo
  2. Installs Python deps
  3. Runs post_instagram.py OR post_linkedin.py with --post-id
  4. The script: uploads assets → creates container → publishes → updates Excel
  5. Commits the updated Excel back to the repo

This pattern is computer-independent — GitHub's cloud runs everything.
"""

from datetime import datetime
from pathlib import Path

import pytz


IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.utc


def ist_to_cron(date_str: str, time_str: str) -> str:
    """Convert 'YYYY-MM-DD' + '7:00 PM' (IST) to a UTC cron expression."""
    time_str = str(time_str).strip()
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %I:%M %p")
    except ValueError:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    dt_ist = IST.localize(dt)
    dt_utc = dt_ist.astimezone(UTC)
    return f"{dt_utc.minute} {dt_utc.hour} {dt_utc.day} {dt_utc.month} *"


def _job_steps(post_id: str, platform: str, planner_rel: str, schedule_cron: str,
               post_name: str = "") -> list:
    """Generate YAML steps for a single post job. Platform = 'ig' or 'li'."""
    script_map = {"ig": "post_instagram.py", "li": "post_linkedin.py"}
    script = script_map[platform]
    platform_label = "Instagram" if platform == "ig" else "LinkedIn"
    safe_post_name = post_name.replace("'", "''")[:60]

    # Required env vars per platform
    env_block = []
    if platform == "ig":
        env_block = [
            "        env:",
            "          IG_USER_ID: ${{ secrets.IG_USER_ID }}",
            "          IG_ACCESS_TOKEN: ${{ secrets.IG_ACCESS_TOKEN }}",
        ]
    else:
        env_block = [
            "        env:",
            "          LI_ACCESS_TOKEN: ${{ secrets.LI_ACCESS_TOKEN }}",
            "          LI_AUTHOR_URN: ${{ secrets.LI_AUTHOR_URN }}",
        ]

    return [
        "      - name: Check out repo",
        "        uses: actions/checkout@v4",
        "        with:",
        "          token: ${{ secrets.GITHUB_TOKEN }}",
        "",
        "      - name: Set up Python",
        "        uses: actions/setup-python@v5",
        "        with:",
        "          python-version: '3.11'",
        "",
        "      - name: Install dependencies",
        "        run: pip install --quiet requests openpyxl pytz python-dotenv Pillow",
        "",
        f"      - name: Post {post_id}",
        "        id: publish",
    ] + env_block + [
        "        run: |",
        f"          python3 _skills/social-post/scripts/{script} \\",
        f"            --post-id {post_id} \\",
        f"            --planner {planner_rel}",
        "",
        "      - name: Commit updated planner status",
        "        if: success()",
        "        run: |",
        "          git config user.email 'bot@example.com'",
        "          git config user.name 'Bhookle Social Bot'",
        f"          git add {planner_rel}",
        f"          git diff --staged --quiet || git commit -m 'auto: mark {post_id} as Posted'",
        "          git push || echo 'Push failed but post succeeded'",
        "",
        "      - name: Email notification (success or failure)",
        "        if: always()",
        "        uses: dawidd6/action-send-mail@v3",
        "        with:",
        "          server_address: smtp.gmail.com",
        "          server_port: 465",
        "          secure: true",
        "          username: ${{ secrets.GMAIL_USER }}",
        "          password: ${{ secrets.GMAIL_APP_PASSWORD }}",
        f"          subject: \"${{{{ job.status == 'success' && '✅ Posted' || '❌ Failed' }}}} {post_id} ({platform_label}): {safe_post_name}\"",
        "          to: ${{ secrets.GMAIL_USER }}",
        "          from: Bhookle Social Bot <${{ secrets.GMAIL_USER }}>",
        "          body: |",
        f"            Post: {post_id} on {platform_label}",
        f"            Title: {safe_post_name}",
        f"            Scheduled cron: {schedule_cron} UTC",
        "            Job status: ${{ job.status }}",
        "            Workflow run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}",
        "",
        "            (Auto-sent by Bhookle Social Bot via GitHub Actions)",
        "",
    ]


def generate_combined_workflow(
    ig_posts: list,
    li_posts: list,
    project_root: Path,
    month_str: str,
    planner_path: Path = None,
) -> Path:
    """
    Generate ONE workflow file containing cron jobs for both IG + LinkedIn.

    Args:
        ig_posts: list of Instagram_Facebook sheet dicts
        li_posts: list of LinkedIn sheet dicts
        project_root: repo root
        month_str: e.g. "2026-05" or "2026-06"

    Returns:
        Path to the generated YAML.
    """
    workflows_dir = project_root / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = workflows_dir / f"bhookle-social-posts-{month_str}.yml"

    # Locate planner Excel (relative to repo root for CI checkout)
    if planner_path and planner_path.exists():
        planner_rel = str(planner_path.relative_to(project_root))
    else:
        # Fall back: most recent xlsx in content-planner/
        candidates = sorted(
            [p for p in (project_root / "content-planner").glob("bhookle-content-calendar-*.xlsx")
             if not p.name.startswith("~$") and ".bak" not in p.name],
            reverse=True
        )
        if candidates:
            planner_rel = str(candidates[0].relative_to(project_root))
        else:
            raise RuntimeError(f"No content planner found in {project_root}/content-planner/")

    # Collect all posts with valid cron times
    job_specs = []  # (post_id, platform, cron_expr, scheduled_iso, name)
    for post in ig_posts:
        pid = str(post.get("PostID", "")).strip()
        pd = str(post.get("PostDate", "")).strip()
        pt = str(post.get("PostTime (IST)", "")).strip()
        pn = str(post.get("PostName", pid)).strip()[:50]
        if not pid or not pd or not pt:
            continue
        try:
            cron = ist_to_cron(pd, pt)
            job_specs.append((pid, "ig", cron, f"{pd} {pt} IST", pn))
        except Exception as e:
            print(f"  ⚠ Skipping {pid}: cannot parse '{pt}' — {e}")
    for post in li_posts:
        pid = str(post.get("PostID", "")).strip()
        pd = str(post.get("PostDate", "")).strip()
        pt = str(post.get("PostTime (IST)", "")).strip()
        pn = str(post.get("PostName", pid)).strip()[:50]
        if not pid or not pd or not pt:
            continue
        try:
            cron = ist_to_cron(pd, pt)
            job_specs.append((pid, "li", cron, f"{pd} {pt} IST", pn))
        except Exception as e:
            print(f"  ⚠ Skipping {pid}: cannot parse '{pt}' — {e}")

    if not job_specs:
        print("  ⚠ No valid jobs to generate")
        return yaml_path

    # Build YAML
    lines = [
        f"# Bhookle Social Posts — {month_str}",
        f"# Auto-generated by social-post skill on {datetime.now().strftime('%Y-%m-%d %H:%M IST')}",
        f"# {len(job_specs)} scheduled posts ({sum(1 for j in job_specs if j[1]=='ig')} IG, "
        f"{sum(1 for j in job_specs if j[1]=='li')} LinkedIn)",
        f"# DO NOT EDIT MANUALLY — regenerate via social_post_runner.py",
        "",
        f"name: Bhookle Social Posts {month_str}",
        "",
        "permissions:",
        "  contents: write   # Required for the bot to commit planner status updates",
        "",
        "on:",
        "  workflow_dispatch:",
        "    inputs:",
        "      post_id:",
        "        description: 'PostID to publish manually (e.g. IG-001 or LI-005)'",
        "        required: true",
        "        type: string",
        "  schedule:",
    ]

    # De-dupe cron expressions for the `on.schedule` block
    seen_crons = set()
    for _, _, cron, scheduled, _ in job_specs:
        if cron not in seen_crons:
            lines.append(f"    - cron: '{cron}'  # {scheduled}")
            seen_crons.add(cron)

    lines += [
        "",
        "jobs:",
        "",
        "  # ────────────────────────────────────────────────────────────────",
        "  # Safe email test — fires only on manual dispatch with post_id=TEST_EMAIL",
        "  # Does NOT post to IG or LinkedIn. Just sends a test email.",
        "  # ────────────────────────────────────────────────────────────────",
        "  test_email:",
        "    name: 'TEST: send test email only (no posting)'",
        "    runs-on: ubuntu-latest",
        "    if: github.event_name == 'workflow_dispatch' && github.event.inputs.post_id == 'TEST_EMAIL'",
        "    steps:",
        "      - name: Send test email",
        "        uses: dawidd6/action-send-mail@v3",
        "        with:",
        "          server_address: smtp.gmail.com",
        "          server_port: 465",
        "          secure: true",
        "          username: ${{ secrets.GMAIL_USER }}",
        "          password: ${{ secrets.GMAIL_APP_PASSWORD }}",
        "          subject: '✅ Bhookle Social Bot — email test'",
        "          to: ${{ secrets.GMAIL_USER }}",
        "          from: Bhookle Social Bot <${{ secrets.GMAIL_USER }}>",
        "          body: |",
        "            This is a test email from the Bhookle Social Bot GitHub Actions workflow.",
        "            If you got this, Gmail SMTP credentials are configured correctly and",
        "            you will receive a similar notification for every IG/LinkedIn post.",
        "",
        "            Workflow run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}",
        "",
    ]

    for pid, platform, cron, scheduled, name in job_specs:
        job_id = pid.lower().replace("-", "_")
        # YAML single-quoted strings: escape ' as ''
        safe_name = name.replace("'", "''")
        # IF clause: trigger only when this post's specific cron fires OR manual dispatch matches
        condition = (
            f"github.event_name == 'workflow_dispatch' && github.event.inputs.post_id == '{pid}' || "
            f"github.event_name == 'schedule' && github.event.schedule == '{cron}'"
        )
        lines += [
            f"  post_{job_id}:",
            f"    name: '{pid}: {safe_name}'",
            "    runs-on: ubuntu-latest",
            f"    if: {condition}",
            "    steps:",
        ] + _job_steps(pid, platform, planner_rel, cron, post_name=name)

    yaml_path.write_text("\n".join(lines))
    print(f"  ✅ Generated {len(job_specs)} cron jobs → {yaml_path.relative_to(project_root)}")
    return yaml_path


# ---------- Legacy alias for backward-compat ----------

def generate_linkedin_workflow(posts, project_root, month_str):
    """DEPRECATED — use generate_combined_workflow(ig_posts=[], li_posts=posts, ...) instead."""
    return generate_combined_workflow([], posts, project_root, month_str)
