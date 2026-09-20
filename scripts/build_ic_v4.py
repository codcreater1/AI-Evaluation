#!/usr/bin/env python3
"""Build datasets/internship-coordinator/v4.jsonl: 50 verified cases.

Same philosophy as v1 (scripts/build_internship_coordinator_dataset.py):
drive the real generator, submit to a real (here: local) instance, record
what actually came back as expected_output. Not invented cases.

Difference from v1: v1 only used the source repo's 9 named scenarios. This
script imports the same `Package` dataclass the generator uses and builds
many parameterized variants of each scenario (different working-day counts,
names, report lengths, etc.) to reach the spec's 50-case minimum, while
staying inside categories the source repo's own rules
(university-rules.json) actually define: min_working_days=20,
min_daily_hours=4.0, max_daily_hours=11.0, min_report_words=500,
min_evaluation_score=60, similarity reject=0.8/warn=0.6.

Corpus safety (PROJECT_PLAN.md's shared-corpus finding): only submissions
landing in status approved/pending/signed join the originality corpus
(app/services/report_repository.py _ACCEPTED_STATUSES). All 7 single-issue
scenario families verifiably return request_clarification (confirmed against
v3.jsonl), so they can share one fresh instance safely. "clean" cases
(approved) are each run on their OWN fresh instance so they can't flag each
other as near-duplicates. "copied" cases run on ONE shared instance seeded
by one clean submission first.

Run against a LOCAL instance (not the live Coolify deployment) - this also
sidesteps the real n8n concurrent-traffic problem documented for the live
system.

Usage:
    python build_ic_v4.py --source-repo /path/to/Internship-report-reviewer \\
        --out datasets/internship-coordinator/v4.jsonl
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import httpx

# Real-world discovery (2026-09-20 live pomelo-2 baseline run): this dataset
# was originally built assuming a fresh/local instance only (see the module
# docstring). Run against the real, never-reset production instance instead,
# 33 of the 39 single-issue cases (everything that used Package()'s default
# report text, unchanged) got wrongly flagged REPORT_NOT_ORIGINAL - because
# that exact default text had already been accepted into pomelo-2's
# persistent corpus by an earlier (v1-v3) baseline run.
#
# First fix attempt (appending one short "reference" sentence to the shared
# default text) measurably FAILED - empirically verified against a
# reproduced contaminated instance: max_similarity only dropped from 0.988 to
# 0.912, still above the 0.8 reject threshold, because TF-IDF cosine
# similarity of two ~600-word documents barely moves when only ~15 words
# differ. What actually works (also empirically verified, same test): a
# genuinely distinct, differently-worded ~550-600 word narrative measures
# ~0.32 similarity against the same contaminated instance - safely under
# even the 0.6 warn threshold. So instead of patching the shared default
# text, every single-issue-family case (SHORT_DAYS/NAME_MISMATCH/UNSIGNED/
# WEEKEND_PAD/FUTURE_DATES/SCAN - none of which override `sections`) and the
# ic-clean-01 seed now get one of two brand-new narratives below
# (SEED_SECTIONS, SHARED_ISSUE_SECTIONS) instead of Package()'s stale
# default. A small per-generation-run marker is layered on top of that on
# every non-copied case for idempotency across repeated runs of the same
# generated file - COPIED_CASES deliberately keep the seed's exact
# text/marker, since their whole point is to be flagged as near-duplicates
# of the seed.
_RUN_NONCE = uuid.uuid4().hex[:12]


def _overrides_with_shared_sections(overrides: dict) -> dict:
    """SHORT_DAYS/NAME_MISMATCH/UNSIGNED/WEEKEND_PAD/FUTURE_DATES/SCAN cases
    never set their own `sections` override - they used to fall through to
    Package()'s stale, already-contaminated default text. Give them the
    fresh SHARED_ISSUE_SECTIONS narrative instead, unless a case already
    specifies its own `sections` (THIN_REPORT_CASES does, deliberately, and
    must keep it)."""
    if "sections" in overrides:
        return overrides
    return {**overrides, "sections": SHARED_ISSUE_SECTIONS}


def _with_marker(pkg, case_id: str):
    """Append a short, unique-per-generation-run section on top of an
    already-distinct report body, so re-running this exact generated file a
    second time against the same persistent target doesn't collide with its
    own first run either."""
    marker_section = (
        "8. Internal Reference",
        f"Internal tracking reference for this submission: {case_id}-{_RUN_NONCE}-"
        f"{secrets.token_hex(4)}.",
    )
    return replace(pkg, sections=[*pkg.sections, marker_section])


SEED_SECTIONS = [
    (
        "1. Introduction",
        "This report covers my nine-week internship on the design systems "
        "team. I came in having used a component library as a consumer on a "
        "class project but had never contributed to one, and had no sense of "
        "how many downstream teams a single shared component actually "
        "touches. This report describes the audit and migration work I did "
        "and how my sense of 'a small change' shifted once I could see its "
        "real blast radius.",
    ),
    (
        "2. Company Overview",
        "The company sells booking software to independent hotels. Product "
        "engineering is organized around a shared React/TypeScript component "
        "library that every one of the six product squads consumes; the "
        "design systems team, which I joined, owns that library plus the "
        "Storybook instance documenting it. Roughly forty engineers depend on "
        "components this team maintains, most of whom I never spoke to "
        "directly.",
    ),
    (
        "3. Work Performed",
        "My main project was auditing every usage of the library's Button "
        "and Input components across the codebase ahead of a planned "
        "accessibility pass, since nobody had an accurate count of how many "
        "call sites passed non-standard props that would break under the new "
        "API. I wrote a small codemod using ts-morph to find and categorize "
        "every call site automatically instead of grepping by hand, which "
        "turned a rumored 'few dozen' usages into a confirmed 311 across "
        "eleven repositories. I then migrated the ones in our own team's "
        "repository myself and wrote a migration guide for the rest, which "
        "another engineer used as the basis for an automated codemod that "
        "handled most of the remaining call sites. In my final three weeks I "
        "added visual regression tests in Chromatic for the six most-used "
        "components, since none existed before and a previous unnoticed "
        "regression had shipped to production for two weeks. I also sat in "
        "on two design-review sessions to see how new components get "
        "approved before they reach the library at all.",
    ),
    (
        "4. Technologies Used",
        "The library is React and TypeScript, documented in Storybook and "
        "published as an internal npm package. I used ts-morph for the "
        "codemod tooling, Chromatic for visual regression testing, and "
        "Figma's API to cross-check component props against their design "
        "specs. Version control was Git with GitHub, and every library "
        "change required two approvals before publishing a new version.",
    ),
    (
        "5. Challenges and Solutions",
        "The hardest part was that 'usage' was not a simple grep target: "
        "the same Button component was sometimes wrapped in a team-local "
        "helper component with a different name, so a naive text search "
        "undercounted real usages by roughly a third. I solved this by "
        "having the codemod resolve imports through the TypeScript compiler "
        "API rather than matching text, which correctly followed re-exports "
        "and wrapper components. The other difficulty was persuading two "
        "squads to schedule the migration during a sprint at all, since it "
        "was invisible user-facing work competing against feature "
        "deadlines; showing the Chromatic diff of the accessibility bug it "
        "fixed made that conversation considerably easier.",
    ),
    (
        "6. Conclusion",
        "I leave this internship with a much better sense of how much "
        "invisible coordination work sits behind something as small as a "
        "button, and how often 'just update the prop' work is really "
        "communication work wearing a code diff. The audit tooling mattered "
        "more to the team long-term than the migration itself, since it is "
        "now reused before every subsequent breaking change.",
    ),
]

SHARED_ISSUE_SECTIONS = [
    (
        "1. Introduction",
        "This report covers my eight-week internship on the infrastructure "
        "team. I had deployed a personal project to a single cloud VM before "
        "starting but had never worked with infrastructure managed as code "
        "or shared across more than one service. This report describes the "
        "provisioning and monitoring work I did over the internship.",
    ),
    (
        "2. Company Overview",
        "The company operates a subscription meal-kit delivery service "
        "across three countries. The infrastructure team is four engineers "
        "supporting roughly thirty production services on AWS, all "
        "provisioned through a shared Terraform codebase. I was assigned to "
        "the on-call rotation as a shadow, not a primary responder, for the "
        "final four weeks of the internship.",
    ),
    (
        "3. Work Performed",
        "My main project was migrating a set of manually-created S3 buckets "
        "and their access policies into the team's existing Terraform "
        "modules, since they had accumulated outside of version control over "
        "roughly two years and nobody had an authoritative record of who "
        "could read from them. I wrote a small script using boto3 to "
        "enumerate every bucket policy and cross-check it against what the "
        "Terraform state expected once imported, which surfaced four buckets "
        "with unexpectedly broad public-read access that predated anyone "
        "still on the team. I imported all of them into Terraform, tightened "
        "the four over-permissive policies after confirming with the owning "
        "teams that nothing depended on the public access, and wrote a "
        "runbook so future buckets get created through Terraform from the "
        "start. Separately, I added CloudWatch alarms for disk usage on the "
        "three services that had run out of disk in the past year, since "
        "none of them had disk-based alerting despite it being the recurring "
        "cause of their incidents.",
    ),
    (
        "4. Technologies Used",
        "Infrastructure is provisioned with Terraform on AWS, with state "
        "stored in a locked S3 backend. I used boto3 for the audit tooling, "
        "CloudWatch for the new alarms, and PagerDuty to see how the "
        "on-call rotation actually gets paged. Everything went through a "
        "Terraform plan review in GitHub before applying.",
    ),
    (
        "5. Challenges and Solutions",
        "The hardest part was that importing existing resources into "
        "Terraform is unforgiving of any drift between the resource's real "
        "state and what the configuration declares, and two of the buckets "
        "had lifecycle rules nobody had documented anywhere. I resolved this "
        "by writing the Terraform configuration to match the resource's "
        "actual current state first, importing it cleanly, and only then "
        "proposing the policy tightening as a separate, reviewable change - "
        "rather than trying to import and fix in the same step. The other "
        "difficulty was confirming nothing depended on the public bucket "
        "access without simply asking on a wide channel and hoping someone "
        "noticed; I instead checked S3 access logs for the two weeks prior "
        "to find every caller before changing anything.",
    ),
    (
        "6. Conclusion",
        "I finish the internship with a much clearer sense of what "
        "'infrastructure as code' actually protects against - not "
        "elegance, but the slow accumulation of undocumented exceptions "
        "that nobody notices until an incident forces someone to reconstruct "
        "them by hand. The audit script mattered more than I expected going "
        "in, since it is the kind of unglamorous tool that only pays off "
        "the second time someone runs it.",
    ),
]

# ---------------------------------------------------------------------------
# Case specs: (case_id, category, package_overrides, notes)
# package_overrides is a dict of Package field -> value, applied via
# dataclasses.replace(Package(), **overrides).
# ---------------------------------------------------------------------------

TODAY = date.today()

# IMPORTANT: each "clean" case's report `sections` text must be genuinely
# different, not just its metadata fields. Empirically confirmed (see
# PROJECT_PLAN.md's shared-corpus finding, and re-verified while building
# this dataset): submitting near-identical report bodies in sequence against
# one instance - exactly how a real experiment run works, concurrency=1,
# one base_url, no restarts between cases - gets cosine similarity ~1.0
# against the first "clean" case and every subsequent one is wrongly
# REJECTED as REPORT_NOT_ORIGINAL. Varying only student_name/company/dates
# (as v1-v3 never needed to, since they only had ONE clean case) is not
# enough. Each set below is a distinct ~550-650 word narrative, matching the
# original's 6-section structure and the university's required-section
# keywords (introduction/company/work performed/technologies/conclusion).

_SECTIONS_02 = [
    (
        "1. Introduction",
        "This report covers my ten-week internship on the payments team. I had "
        "written a toy checkout flow for a class project before starting but "
        "had never worked with money that had to reconcile against a "
        "third-party ledger to the cent. This report describes the "
        "reconciliation tooling I built and what handling other people's "
        "money changed about how carefully I write code.",
    ),
    (
        "2. Company Overview",
        "The company sells subscription software to independent dental "
        "clinics. The payments team is three engineers responsible for "
        "billing roughly nine thousand clinics monthly through Stripe, and "
        "for reconciling what Stripe reports against what the internal "
        "ledger expects. A mismatch of even a few cents across enough "
        "invoices had, before this internship, occasionally taken a full day "
        "to track down manually.",
    ),
    (
        "3. Work Performed",
        "My main project was building a nightly reconciliation job that "
        "pulls Stripe's payout report and diffs it line by line against the "
        "internal ledger, flagging any invoice where the two disagree by "
        "more than a cent. Before this existed, reconciliation was a "
        "spreadsheet one engineer rebuilt by hand every month, and it had "
        "silently missed a batch of double-charged clinics for two billing "
        "cycles before anyone noticed from a support ticket. I found the "
        "root cause of that specific double-charge bug while building the "
        "tool - a webhook retry that wasn't idempotent - and fixed it "
        "separately from the reconciliation job itself. In my last four "
        "weeks I added a small internal dashboard so support could look up a "
        "clinic's reconciliation status without asking an engineer, which "
        "cut a recurring category of internal Slack questions considerably. "
        "Building the reconciliation job also meant reading through eight "
        "months of the manual spreadsheet's change history to understand "
        "which discrepancies had historically been ignored as 'known noise' "
        "versus which had turned out to be real bugs, since the automated "
        "job needed to make that same judgment call without a human "
        "glancing at the number first. Several of the 'known noise' entries "
        "turned out to be the same proration rounding issue happening "
        "repeatedly, which nobody had connected across months because each "
        "instance was investigated in isolation by whichever engineer was "
        "on support rotation that week.",
    ),
    (
        "4. Technologies Used",
        "The billing service is Python with Stripe's API and webhooks. I "
        "used Postgres for the ledger, a scheduled job runner for the "
        "nightly reconciliation, and a small internal React dashboard for "
        "the support-facing lookup tool. Every change to the billing service "
        "required two reviewers given how directly it touched money.",
    ),
    (
        "5. Challenges and Solutions",
        "The hardest part was that Stripe's payout report and the internal "
        "ledger use different rounding rules for prorated mid-cycle plan "
        "changes, which looked identical to a real discrepancy until I "
        "traced four false-positive flags back to the same rounding "
        "difference. I resolved it by normalizing both sides to the same "
        "rounding rule before comparing, rather than trying to special-case "
        "every proration scenario. The other difficulty was convincing the "
        "team that idempotency keys were worth the added complexity before "
        "the double-charge bug was found - after it was found, that "
        "conversation was considerably shorter.",
    ),
    (
        "6. Conclusion",
        "I finish this internship with a much more careful relationship to "
        "code that touches money specifically - not because the code itself "
        "is harder, but because a silent one-cent-per-invoice bug can hide "
        "for months in a way a crashing bug cannot. The reconciliation tool "
        "mattered more to the team than I expected going in, mostly because "
        "it turns an invisible problem into a visible list.",
    ),
]

_SECTIONS_03 = [
    (
        "1. Introduction",
        "This report covers my eleven-week internship on the search and "
        "recommendations team. I had used a library's built-in search bar "
        "in a class project before but had never worked with anything "
        "involving relevance ranking. This report describes the ranking "
        "experiment I ran and what surprised me about tuning a system where "
        "'better' is not a single obvious metric.",
    ),
    (
        "2. Company Overview",
        "The company runs a marketplace for secondhand musical instruments. "
        "The search and recommendations team owns the search bar and the "
        "'similar listings' module on every item page, both backed by "
        "Elasticsearch with a re-ranking layer on top. The team ships "
        "ranking changes behind an internal experimentation platform rather "
        "than to everyone at once.",
    ),
    (
        "3. Work Performed",
        "My main project was investigating why searches for specific brand "
        "names were returning accessories before the instruments themselves "
        "- a recurring complaint in support tickets that nobody had "
        "root-caused. I found that the ranking model weighted exact text "
        "match heavily, and accessory listings often repeated the brand name "
        "several times in their description while instrument listings "
        "mentioned it once, in the title. I built a small offline evaluation "
        "set of forty real queries with human-judged relevant results to "
        "measure any ranking change against, since the team had been making "
        "ranking decisions from anecdote before this. Using that evaluation "
        "set, I tested down-weighting description-text matches relative to "
        "title matches and category, which fixed the brand-name issue "
        "without regressing the queries that had been working correctly. I "
        "shipped this behind an experiment to five percent of search traffic "
        "in my final two weeks and it was still running, with a positive "
        "early read, when the internship ended. Before shipping even the "
        "small experiment, I spent time convincing a skeptical teammate that "
        "the brand-name issue was worth fixing at all, since it affected a "
        "narrow slice of queries and the team's roadmap was already full of "
        "higher-traffic ranking work. Walking through five real support "
        "tickets from sellers whose instrument listings had been effectively "
        "buried by their own accessory listings turned out to be more "
        "persuasive than the aggregate query-volume argument I had originally "
        "prepared.",
    ),
    (
        "4. Technologies Used",
        "Search is Elasticsearch with a custom scoring script, with the "
        "re-ranking layer in Python. I built the offline evaluation set as a "
        "CSV scored through a small script, and the live experiment ran "
        "through the company's existing internal experimentation platform. "
        "Everything went through a ranking-change review with two other "
        "engineers before touching real traffic.",
    ),
    (
        "5. Challenges and Solutions",
        "The hardest part was that the forty-query evaluation set was small "
        "enough that a single judgment call on one ambiguous query could "
        "swing the aggregate metric noticeably, which nearly led the team to "
        "reject a genuinely good change because of one query I had judged "
        "inconsistently with the rest. I fixed this by having a second "
        "person independently judge the same forty queries and only keeping "
        "the ones where we agreed, which shrank the set to thirty-one but "
        "made the metric trustworthy enough to act on. The other difficulty "
        "was that support tickets are a biased sample of search problems, "
        "since most bad results never get reported at all.",
    ),
    (
        "6. Conclusion",
        "I leave this internship with a much clearer sense of why ranking "
        "work is slow even when a fix seems obvious in hindsight - the fix "
        "was one line, but trusting that it was actually an improvement "
        "took most of the internship. Building the evaluation set mattered "
        "more long-term than the specific fix, since the team is still using "
        "it to judge later ranking changes.",
    ),
]

_SECTIONS_04 = [
    (
        "1. Introduction",
        "This report covers my seven-week internship on the developer "
        "experience team, working on the public API documentation site. I "
        "had written README files before but had never worked on "
        "documentation treated as a product with its own metrics. This "
        "report describes the documentation restructuring I did and what "
        "changed in how I think about writing for someone who is stuck.",
    ),
    (
        "2. Company Overview",
        "The company provides an API for verifying shipping addresses "
        "internationally. The developer experience team of two owns the "
        "public docs site, built from Markdown source into a static site, "
        "and tracks which pages people land on right before contacting "
        "support - a strong signal that the page failed to answer their "
        "question.",
    ),
    (
        "3. Work Performed",
        "My main project was rewriting the authentication and error-handling "
        "pages, which support tickets showed were the two most common "
        "reasons a new integrator gave up before their first successful "
        "request. I read through three months of support tickets tagged "
        "'integration help' to find the specific confusions - most "
        "integrators were not confused about the concept of an API key, but "
        "about which of three header formats the docs' code samples "
        "inconsistently used. I rewrote both pages with a single consistent "
        "header format across every code sample, added a runnable example "
        "for the five most common error codes instead of just describing "
        "them, and restructured the error-handling page around 'what do I "
        "do about this' rather than an alphabetical list of error names. In "
        "my last three weeks I added a feedback widget to both pages so "
        "future confusion would show up as data instead of requiring another "
        "manual ticket review. Reading three months of tickets also surfaced "
        "a smaller, unrelated pattern: a noticeable fraction of integrators "
        "copy-pasted a code sample verbatim, including a placeholder API key "
        "that looked plausible enough to try before failing, then filed a "
        "ticket assuming the sample itself was broken. I changed every "
        "placeholder key across the docs site to an obviously fake format "
        "instead of a plausible-looking one, which was a small change but "
        "addressed a confusion the ticket-tag analysis alone would never "
        "have surfaced.",
    ),
    (
        "4. Technologies Used",
        "The docs site is built with a static site generator from Markdown "
        "and MDX for the interactive code samples, deployed on every merge "
        "to the main branch. I used the support ticketing system's search "
        "to pull the three months of tickets, and a simple embedded widget "
        "for the new feedback mechanism. Every docs change went through a "
        "review from someone on the API team itself, not just the docs "
        "team, to check technical accuracy.",
    ),
    (
        "5. Challenges and Solutions",
        "The hardest part was that 'most common ticket topic' and 'most "
        "common actual confusion' were not the same thing - many tickets "
        "tagged 'authentication error' turned out, once I read the full "
        "thread, to actually be about a rate limit being misreported as an "
        "auth failure. I solved this by reading full ticket threads rather "
        "than trusting the tag, which took longer but meant the rewrite "
        "targeted the real problem instead of the mislabeled one. The other "
        "difficulty was writing error-handling guidance without access to "
        "the error-handling code itself, which meant several rounds of "
        "review with the API team to catch cases my ticket-reading had "
        "missed.",
    ),
    (
        "6. Conclusion",
        "I finish the internship with a much better sense of documentation "
        "as something you debug rather than something you write once. The "
        "feedback widget mattered more than the rewrite itself in the long "
        "run, since it is the first time the team has ongoing evidence of "
        "which pages are still failing people.",
    ),
]

_SECTIONS_05 = [
    (
        "1. Introduction",
        "This report covers my nine-week internship on the localization "
        "team. I had toggled a language setting as a user before but had "
        "never seen what breaks a translated interface from the inside. "
        "This report describes the string-extraction audit I did and what "
        "it taught me about assumptions baked into code that only show up "
        "in a language nobody on the team spoke natively.",
    ),
    (
        "2. Company Overview",
        "The company operates a flight and hotel booking site available in "
        "nine languages. The localization team of three coordinates with an "
        "external translation vendor and maintains the tooling that "
        "extracts translatable strings from the codebase into files the "
        "vendor works from. Arabic and Hebrew support, added the year before "
        "I joined, had introduced right-to-left layout bugs that were still "
        "being found by users rather than caught before release.",
    ),
    (
        "3. Work Performed",
        "My main project was auditing the checkout flow for hardcoded "
        "strings that had bypassed the translation extraction tooling "
        "entirely, which the vendor could not translate because their "
        "tooling never saw them. I wrote a script that rendered every "
        "checkout page and flagged any visible text not present in the "
        "extracted string files, which found eighteen hardcoded strings "
        "across error messages and a confirmation modal that had shipped in "
        "English to all nine locales for months. I fixed the extraction gaps "
        "so those eighteen strings now flow through the normal translation "
        "pipeline, and separately found three right-to-left layout bugs in "
        "the same checkout flow while manually testing the Arabic version "
        "after the string fixes, which I filed but did not fix myself given "
        "the remaining time. The script itself took longer to get right than "
        "expected, since the headless browser needed to wait for "
        "asynchronously-loaded checkout steps before comparing visible text, "
        "and an early version flagged dozens of false positives from text "
        "that had simply not finished rendering yet. I fixed that by waiting "
        "on a specific loading indicator's disappearance rather than a fixed "
        "delay, which also made the audit noticeably faster to re-run after "
        "each extraction fix.",
    ),
    (
        "4. Technologies Used",
        "The extraction tooling is a custom script wrapping a standard i18n "
        "library, generating JSON string files the translation vendor "
        "consumes. I wrote the checkout audit script in Python using a "
        "headless browser to render each page and inspect visible text "
        "against the extracted strings. Every extraction-tooling change went "
        "through review from a senior engineer on the team.",
    ),
    (
        "5. Challenges and Solutions",
        "The hardest part was that some hardcoded strings only appeared "
        "conditionally - one error message only rendered when a specific "
        "payment method failed validation in a specific way, which my first "
        "audit pass never triggered. I found the rest by reading the "
        "checkout flow's source directly for string literals rather than "
        "relying only on rendered-page auditing, which was slower but "
        "caught the conditional cases. The other difficulty was that nobody "
        "on the team read Arabic well enough to judge whether a layout 'bug' "
        "was actually wrong or just unfamiliar, which I addressed by sharing "
        "screenshots with the translation vendor's native-speaking reviewers "
        "rather than guessing internally.",
    ),
    (
        "6. Conclusion",
        "I leave this internship with a real appreciation for how much of "
        "localization work is finding text that nobody thought of as "
        "'content' in the first place - error messages, modals, anything "
        "written in a hurry. The extraction-gap fixes will keep paying off "
        "on every future string added to checkout, which is more durable "
        "than the individual bugs I found.",
    ),
]

_SECTIONS_06 = [
    (
        "1. Introduction",
        "This report covers my six-week internship on the growth analytics "
        "team. I had computed summary statistics for a class project before "
        "but had never had to defend a number to people who would make a "
        "budget decision based on it. This report describes the attribution "
        "investigation I did and what changed in how skeptically I read my "
        "own analysis.",
    ),
    (
        "2. Company Overview",
        "The company sells an budgeting app directly to consumers, "
        "acquiring users through a mix of paid social ads and an affiliate "
        "referral program. The growth analytics team of two maintains the "
        "event pipeline and the attribution model that decides which "
        "acquisition channel gets credit for a given signup, which directly "
        "feeds next month's ad spend decisions.",
    ),
    (
        "3. Work Performed",
        "My main project was investigating why the affiliate channel's "
        "reported signups had jumped forty percent in a single week with no "
        "corresponding change in affiliate traffic, which the team suspected "
        "was a measurement problem rather than a real trend before assigning "
        "it any budget significance. I traced the event pipeline and found "
        "that a recent app update had changed how the referral code was "
        "captured on a specific onboarding screen, causing some organic "
        "signups to be mis-attributed to a default affiliate code used in "
        "testing. I quantified the actual overcount at roughly twenty-eight "
        "percent of the reported jump by cross-referencing against a "
        "separate, unaffected event, and fixed the capture bug so the "
        "referral code only records when a real code is present. In my last "
        "two weeks I added a validation check that would have caught this "
        "specific bug automatically, comparing attribution totals against "
        "the unaffected event weekly. Quantifying the twenty-eight percent "
        "overcount also meant ruling out two other candidate explanations "
        "first - a concurrent ad campaign launch and a seasonal pattern from "
        "the prior year - by checking whether either one predicted the exact "
        "week of the jump as precisely as the app update did. Neither did, "
        "which made the app-update explanation considerably more defensible "
        "than it would have been from timing alone.",
    ),
    (
        "4. Technologies Used",
        "The event pipeline is Segment feeding into a warehouse, queried "
        "with SQL for the investigation. I used a notebook for the "
        "cross-referencing analysis and built the new validation check as a "
        "scheduled query with an alert. Every change to the attribution "
        "logic itself required sign-off from the growth lead given how "
        "directly it affected budget decisions.",
    ),
    (
        "5. Challenges and Solutions",
        "The hardest part was proving the overcount was a measurement bug "
        "and not real growth without simply asserting it, since a forty "
        "percent jump is also what real viral growth would look like in the "
        "same data. I resolved this by finding an unaffected event that "
        "should move together with real growth but would not be touched by "
        "the attribution bug, and showing the two had diverged exactly when "
        "the app update shipped. The other difficulty was that the growth "
        "lead had already mentioned the forty percent number in a leadership "
        "update before I finished the investigation, which made delivering "
        "the correction a more sensitive conversation than the analysis "
        "itself.",
    ),
    (
        "6. Conclusion",
        "I finish this internship considerably more suspicious of any "
        "metric that moves suddenly without an obvious cause, in a good "
        "way. The validation check mattered more than the one-time "
        "correction, since it means the next version of this exact bug gets "
        "caught before it reaches a leadership update instead of after.",
    ),
]

CLEAN_CASES = [
    ("ic-clean-01", {}),
    (
        "ic-clean-02",
        {
            "student_name": "Aleksandra Kowal",
            "student_id": "s25011",
            "company": "Baltic Freight Systems Sp. z o.o.",
            "department": "Data Platform Team",
            "supervisor_name": "Piotr Zielinski",
            "supervisor_title": "Staff Engineer",
            "working_days": 25,
            "daily_hours": 7.5,
            "sections": _SECTIONS_02,
        },
    ),
    (
        "ic-clean-03",
        {
            "student_name": "Michal Wojcik",
            "student_id": "s25032",
            "company": "Harbor Analytics S.A.",
            "working_days": 20,  # exact boundary, still valid
            "daily_hours": 8.0,
            "sections": _SECTIONS_03,
        },
    ),
    (
        "ic-clean-04",
        {
            "student_name": "Katarzyna Lis",
            "student_id": "s25048",
            "daily_hours": 11.0,  # max valid boundary
            "sections": _SECTIONS_04,
        },
    ),
    (
        "ic-clean-05",
        {
            "student_name": "Filip Nowicki",
            "student_id": "s25059",
            "daily_hours": 4.0,  # min valid boundary
            "sections": _SECTIONS_05,
        },
    ),
    (
        "ic-clean-06",
        {
            "student_name": "Ewa Szymanska",
            "student_id": "s25066",
            "scores": {
                "Technical Competence": 61,
                "Communication": 62,
                "Punctuality": 60,
                "Initiative": 63,
                "Teamwork": 60,
            },
            "overall_score": 61,  # just above min_evaluation_score=60
            "sections": _SECTIONS_06,
        },
    ),
]

SHORT_DAYS_CASES = [
    ("ic-short-days-01", {"working_days": 1}),
    ("ic-short-days-02", {"working_days": 5}),
    ("ic-short-days-03", {"working_days": 10}),
    ("ic-short-days-04", {"working_days": 14}),
    ("ic-short-days-05", {"working_days": 17}),
    ("ic-short-days-06", {"working_days": 19}),  # one day short of the 20 min
]

NAME_MISMATCH_CASES = [
    ("ic-name-mismatch-01", {"evaluation_student_name": "Jakub Nowak"}),
    ("ic-name-mismatch-02", {"evaluation_student_name": "Anna Kaminska"}),
    ("ic-name-mismatch-03", {"evaluation_student_name": "Tomasz Wroblewski"}),
    ("ic-name-mismatch-04", {"evaluation_student_name": "Magdalena Duda"}),
    ("ic-name-mismatch-05", {"evaluation_student_name": "Z. Wisniewska"}),  # partial/initialed
]

UNSIGNED_CASES = [
    ("ic-unsigned-01", {"signed": False, "stamped": True}),
    ("ic-unsigned-02", {"signed": True, "stamped": False}),
    ("ic-unsigned-03", {"signed": False, "stamped": False}),
    ("ic-unsigned-04", {"signed": False, "stamped": True, "student_name": "Dawid Krol"}),
    ("ic-unsigned-05", {"signed": True, "stamped": False, "student_name": "Julia Pawlak"}),
    ("ic-unsigned-06", {"signed": False, "stamped": False, "student_name": "Kacper Wysocki"}),
]

_SHORT_SECTION_SETS = [
    [
        ("1. Introduction", "I did an internship at a software company."),
        ("2. Company Overview", "It is a logistics company."),
        ("3. Work Performed", "I wrote some code and fixed some bugs."),
        ("4. Technologies Used", "Python."),
        ("5. Challenges and Solutions", "It was hard at first."),
        ("6. Conclusion", "I learned a lot. Thank you."),
    ],
    [
        ("1. Introduction", "This is my internship report."),
        ("2. Company Overview", "A small startup."),
        ("3. Work Performed", "Backend tickets."),
        ("4. Technologies Used", "Go and Postgres."),
        ("5. Challenges and Solutions", "Deadlines were tight."),
        ("6. Conclusion", "Good experience overall."),
    ],
    [
        ("1. Introduction", "Summer internship, twelve weeks, remote."),
        ("2. Company Overview", "Mid-size fintech company."),
        ("3. Work Performed", "QA and some scripting."),
        ("4. Technologies Used", "JavaScript."),
        ("5. Challenges and Solutions", "Onboarding was slow."),
        ("6. Conclusion", "Would recommend the team."),
    ],
    [
        ("1. Introduction", "Short placement in the support team."),
        ("2. Company Overview", "B2B SaaS vendor."),
        ("3. Work Performed", "Answered tickets, wrote docs."),
        ("4. Technologies Used", "Zendesk, Notion."),
        ("5. Challenges and Solutions", "Volume was high some weeks."),
        ("6. Conclusion", "Learned a lot about customers."),
    ],
    [
        ("1. Introduction", "Six-week internship on the mobile team."),
        ("2. Company Overview", "Consumer app company, ~40 engineers."),
        ("3. Work Performed", "UI bugs and one small feature."),
        ("4. Technologies Used", "Kotlin."),
        ("5. Challenges and Solutions", "Simulator flakiness."),
        ("6. Conclusion", "Enjoyed the mobile stack."),
    ],
    [
        ("1. Introduction", "N/A - report written quickly."),
        ("2. Company Overview", "N/A"),
        ("3. Work Performed", "Did some tasks."),
        ("4. Technologies Used", "N/A"),
        ("5. Challenges and Solutions", "N/A"),
        ("6. Conclusion", "N/A"),
    ],
]
THIN_REPORT_CASES = [
    (f"ic-thin-report-{i+1:02d}", {"sections": sections})
    for i, sections in enumerate(_SHORT_SECTION_SETS)
]

WEEKEND_PAD_CASES = [
    ("ic-weekend-pad-01", {"working_days": 20, "include_weekends": True, "day_offset": 4}),
    ("ic-weekend-pad-02", {"working_days": 20, "include_weekends": True, "day_offset": 2}),
    ("ic-weekend-pad-03", {"working_days": 22, "include_weekends": True, "day_offset": 4}),
    ("ic-weekend-pad-04", {"working_days": 20, "include_weekends": True, "day_offset": 6}),
    ("ic-weekend-pad-05", {"working_days": 25, "include_weekends": True, "day_offset": 3}),
    ("ic-weekend-pad-06", {"working_days": 20, "include_weekends": True, "day_offset": 1}),
]

FUTURE_DATES_CASES = [
    (
        "ic-future-dates-01",
        {
            "start_date": TODAY - timedelta(days=5),
            "end_date": TODAY + timedelta(days=40),
            "evaluation_date": TODAY + timedelta(days=43),
            "day_offset": 0,
        },
    ),
    (
        "ic-future-dates-02",
        {
            "start_date": TODAY - timedelta(days=10),
            "end_date": TODAY + timedelta(days=10),
            "evaluation_date": TODAY + timedelta(days=13),
            "day_offset": 0,
        },
    ),
    (
        "ic-future-dates-03",
        {
            "start_date": TODAY + timedelta(days=1),
            "end_date": TODAY + timedelta(days=60),
            "evaluation_date": TODAY + timedelta(days=63),
            "day_offset": 0,
        },
    ),
    (
        "ic-future-dates-04",
        {
            "start_date": TODAY - timedelta(days=30),
            "end_date": TODAY + timedelta(days=1),
            "evaluation_date": TODAY + timedelta(days=4),
            "day_offset": 0,
        },
    ),
    (
        "ic-future-dates-05",
        {
            "start_date": TODAY - timedelta(days=2),
            "end_date": TODAY + timedelta(days=90),
            "evaluation_date": TODAY + timedelta(days=93),
            "day_offset": 0,
        },
    ),
]

SCAN_CASES = [
    ("ic-scan-01", {"report_as_image": True}),
    ("ic-scan-02", {"report_as_image": True, "student_name": "Bartosz Adamski"}),
    ("ic-scan-03", {"report_as_image": True, "company": "Riverside Tech Sp. z o.o."}),
    ("ic-scan-04", {"report_as_image": True, "working_days": 15}),
    ("ic-scan-05", {"report_as_image": True, "signed": False}),
]

# copied cases: each copies the SEED clean report's text, submitted by a
# different student. All run on the SAME instance, after the seed.
COPIED_CASES = [
    ("ic-copied-01", {"student_name": "Tomasz Lewandowski", "student_id": "s24902"}),
    ("ic-copied-02", {"student_name": "Igor Baran", "student_id": "s24913"}),
    ("ic-copied-03", {"student_name": "Natalia Ostrowska", "student_id": "s24924"}),
    ("ic-copied-04", {"student_name": "Kamil Sikora", "student_id": "s24935"}),
    ("ic-copied-05", {"student_name": "Weronika Czarnecka", "student_id": "s24946"}),
]

SINGLE_ISSUE_GROUPS = [
    ("short-days", "incomplete_information", SHORT_DAYS_CASES),
    ("name-mismatch", "conflicting_information", NAME_MISMATCH_CASES),
    ("unsigned", "missing_documents", UNSIGNED_CASES),
    ("thin-report", "incomplete_information", THIN_REPORT_CASES),
    ("weekend-pad", "edge_case", WEEKEND_PAD_CASES),
    ("future-dates", "edge_case", FUTURE_DATES_CASES),
    ("scan", "unreadable_document", SCAN_CASES),
]


def _port_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait_healthy(port: int, timeout_s: float = 15) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).raise_for_status()
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise RuntimeError(f"Service on port {port} never became healthy")


def _start_service(source_repo: Path, port: int, db_path: Path, storage_root: Path):
    venv_uvicorn = source_repo / "backend" / ".venv" / "bin" / "uvicorn"
    uvicorn_bin = str(venv_uvicorn) if venv_uvicorn.exists() else "uvicorn"
    db_path.unlink(missing_ok=True)
    if storage_root.exists():
        shutil.rmtree(storage_root)
    proc = subprocess.Popen(
        [uvicorn_bin, "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(source_repo / "backend"),
        env={
            "PATH": "/usr/bin:/bin",
            "REVIEW_DB_PATH": str(db_path),
            "REVIEW_STORAGE_ROOT": str(storage_root),
            "LLM_API_KEY": "",  # offline mode, same as the repo's own test suite
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_healthy(port)
    return proc


def _stop_service(proc, db_path: Path, storage_root: Path) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    db_path.unlink(missing_ok=True)
    if storage_root.exists():
        shutil.rmtree(storage_root)


def _submit(port: int, doc_dir: Path, application_id: str) -> dict:
    files = [
        ("files", (name, (doc_dir / name).read_bytes(), "application/pdf"))
        for name in ("internship_report.pdf", "evaluation_form.pdf", "attendance_record.pdf")
    ]
    data = {"intern_email": "student@example.edu", "application_id": application_id}
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"http://127.0.0.1:{port}/reports/", data=data, files=files)
        resp.raise_for_status()
        return resp.json()


def _to_case(case_id: str, scenario_family: str, category: str, doc_dir: Path, response: dict) -> dict:
    status = response["status"]
    finding_codes = sorted({f["code"] for f in response.get("findings", [])})
    attachments = [
        {
            "filename": name,
            "content_base64": base64.b64encode((doc_dir / name).read_bytes()).decode("ascii"),
        }
        for name in ("internship_report.pdf", "evaluation_form.pdf", "attendance_record.pdf")
    ]
    return {
        "id": case_id,
        "system": "internship-coordinator",
        "input": {
            "intern_email": "student@example.edu",
            "application_id": case_id,
            "attachments": attachments,
        },
        "expected_output": {
            "status": status,
            "must_include_finding_codes": finding_codes,
            "student_name": response.get("student_name"),
            "student_id": response.get("student_id"),
            "company": response.get("company"),
        },
        "metadata": {
            "scenario_family": scenario_family,
            "category": category,
            "source": "generated via build_ic_v4.py (Package-level variations of "
            "Internship-report-reviewer's own testdocs/tool/completion_docs.py), "
            "run against a real LOCAL instance",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, default=Path("datasets/internship-coordinator/v4.jsonl")
    )
    parser.add_argument("--samples-dir", type=Path, default=Path("/tmp/ic-v4-samples"))
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()

    if not (args.source_repo / "backend" / "app" / "main.py").exists():
        sys.exit(f"{args.source_repo} doesn't look like an Internship-report-reviewer checkout")

    sys.path.insert(0, str(args.source_repo / "testdocs" / "tool"))
    from completion_docs import Package, write_attendance, write_evaluation, write_report  # noqa: E402

    args.samples_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []

    def render(pkg: Package, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        write_report(pkg, out_dir / "internship_report.pdf")
        write_evaluation(pkg, out_dir / "evaluation_form.pdf")
        write_attendance(pkg, out_dir / "attendance_record.pdf")
        return out_dir

    db_path = args.source_repo / "backend" / "_ds_v4.db"
    storage = args.source_repo / "backend" / "_ds_v4_tmp"

    # --- Group 1: the 7 single-issue families, one shared fresh instance ---
    # (safe: all verifiably return request_clarification, confirmed via v3,
    # so none of them join the originality corpus.)
    proc = _start_service(args.source_repo, args.port, db_path, storage)
    try:
        for scenario_family, category, case_list in SINGLE_ISSUE_GROUPS:
            for case_id, overrides in case_list:
                overrides = _overrides_with_shared_sections(overrides)
                pkg = _with_marker(replace(Package(), **overrides), case_id)
                doc_dir = render(pkg, args.samples_dir / case_id)
                response = _submit(args.port, doc_dir, case_id)
                if response["status"] in ("approved", "pending", "signed"):
                    print(
                        f"!! WARNING: {case_id} unexpectedly got status="
                        f"{response['status']!r} (joins corpus) - flag for manual review"
                    )
                cases.append(_to_case(case_id, scenario_family, category, doc_dir, response))
                print(f"{case_id:22s} -> status={response['status']}")
    finally:
        _stop_service(proc, db_path, storage)

    # --- Group 2: 5 of the 6 "clean" cases, each on its OWN fresh instance
    # (so they can't flag each other as near-duplicate originality hits) ---
    for case_id, overrides in CLEAN_CASES[1:]:
        pkg = _with_marker(replace(Package(), **overrides), case_id)
        doc_dir = render(pkg, args.samples_dir / case_id)
        proc = _start_service(args.source_repo, args.port, db_path, storage)
        try:
            response = _submit(args.port, doc_dir, case_id)
        finally:
            _stop_service(proc, db_path, storage)
        cases.append(_to_case(case_id, "clean", "valid_application", doc_dir, response))
        print(f"{case_id:22s} -> status={response['status']}")

    # --- Group 3: seed clean (ic-clean-01) + 5 copied cases, one shared
    # fresh instance, clean submitted first ---
    proc = _start_service(args.source_repo, args.port, db_path, storage)
    try:
        seed_id, seed_overrides = CLEAN_CASES[0]
        seed_overrides = {**seed_overrides, "sections": SEED_SECTIONS}
        seed_pkg = _with_marker(replace(Package(), **seed_overrides), seed_id)
        seed_dir = render(seed_pkg, args.samples_dir / seed_id)
        seed_response = _submit(args.port, seed_dir, seed_id)
        cases.append(_to_case(seed_id, "clean", "valid_application", seed_dir, seed_response))
        print(f"{seed_id:22s} -> status={seed_response['status']}")

        for case_id, overrides in COPIED_CASES:
            pkg = replace(seed_pkg, **overrides)  # same report text, different student
            doc_dir = render(pkg, args.samples_dir / case_id)
            response = _submit(args.port, doc_dir, case_id)
            cases.append(_to_case(case_id, "copied", "originality_violation", doc_dir, response))
            print(f"{case_id:22s} -> status={response['status']}")
    finally:
        _stop_service(proc, db_path, storage)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"\nWrote {args.out} with {len(cases)} cases.")
    by_status: dict[str, int] = {}
    for c in cases:
        by_status[c["expected_output"]["status"]] = by_status.get(c["expected_output"]["status"], 0) + 1
    print("Status breakdown:", by_status)


if __name__ == "__main__":
    main()
