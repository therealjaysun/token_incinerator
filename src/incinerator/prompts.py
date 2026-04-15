from __future__ import annotations

from typing import Callable

from incinerator.types import BurnPrompt, PromptCategory, RepoFile

_PLAN_ONLY_SUFFIX = (
    "\n\nIMPORTANT: This is a planning and analysis exercise only. "
    "Do not execute any commands, do not write any files, do not make any git commits or pushes. "
    "Provide your analysis and recommendations in text only."
)

_TEMPLATES: dict[PromptCategory, str] = {
    "review": """\
Perform a thorough, senior-engineer-level code review of this codebase. Start by reading each of \
the following files in full:

{file_list}

After reading them, identify:
1. All code quality issues (naming, complexity, duplication, dead code)
2. All architectural concerns (coupling, cohesion, separation of concerns)
3. All potential bugs and edge cases
4. All performance bottlenecks
5. All missing error handling
6. All opportunities for simplification

For each issue, cite the exact file and line range, explain why it is a problem, and provide a \
specific, concrete recommendation with example code where applicable. Be exhaustive — this review \
will be used by the team to plan a significant refactor sprint.{suffix}""",

    "refactor": """\
You are tasked with producing a comprehensive refactoring plan for this codebase. Begin by reading \
each of the following files completely:

{file_list}

Then read any files they import that seem relevant. Produce a detailed refactoring plan that covers:
1. Identify every function/class that violates the Single Responsibility Principle
2. Map all circular dependencies and propose resolution strategies
3. Identify duplicated logic and design shared abstractions to eliminate it
4. Propose a new module/package structure with rationale
5. List every public API that should be changed and how
6. Write out the full, new version of the three most complex files after refactoring
7. Estimate the risk level of each change (low/medium/high) with justification

Be specific and detailed — include actual proposed code, not just high-level descriptions.{suffix}""",

    "security_audit": """\
Conduct a comprehensive security audit of this codebase. Start by reading each of these files \
thoroughly:

{file_list}

Then trace all data flows from external inputs to outputs. Produce a detailed threat model and \
vulnerability report covering:
1. All injection vulnerabilities (SQL, command, LDAP, XPath, etc.) — cite exact locations
2. All authentication and authorization flaws
3. All cryptographic weaknesses (weak algorithms, hardcoded secrets, improper key management)
4. All insecure deserialization paths
5. All sensitive data exposure risks
6. All SSRF, XXE, and path traversal vulnerabilities
7. All business logic flaws
8. CVSS score for each finding (Base, Temporal, Environmental)
9. Specific remediation code for each Critical and High severity finding

Map every finding to a CWE identifier. Be thorough — this will be submitted to a compliance \
auditor.{suffix}""",

    "doc_generation": """\
Generate comprehensive, production-grade documentation for this codebase. Read each of these \
files in full:

{file_list}

Then read any additional files needed to fully understand the system. Produce:
1. A high-level architecture overview with a textual diagram (ASCII art)
2. A developer guide explaining how to set up, run, and test the project
3. Full API reference documentation for every public function, class, and module (with type \
signatures, parameter descriptions, return values, exceptions raised, and usage examples)
4. A troubleshooting guide covering the 10 most likely failure modes
5. A glossary of domain terms used in the codebase
6. A changelog template showing how to document breaking changes

Write in clear, precise technical prose. Every code example should be runnable.{suffix}""",

    "architecture": """\
Perform a deep architectural analysis of this codebase and produce a full architectural \
improvement proposal. Start by reading these files:

{file_list}

Then explore the broader codebase as needed. Your analysis must include:
1. Current architecture description (draw ASCII diagrams of the component relationships)
2. Identification of all architectural anti-patterns present (Big Ball of Mud, God Object, \
Spaghetti Code, Leaky Abstraction, etc.)
3. Scalability analysis — where will this system break under 10x, 100x load?
4. A proposed target architecture with rationale, migration path, and risk assessment
5. Three alternative architectural approaches with detailed trade-off comparison (include a \
decision matrix)
6. Specific, actionable tickets for the first three sprints of the migration
7. A list of architecture decision records (ADRs) that should be written

Include concrete examples and diagrams throughout.{suffix}""",
}


def generate_prompt(
    category: PromptCategory,
    files: list[RepoFile],
    random_fn: Callable[[], float],
) -> BurnPrompt:
    file_list = "\n".join(f"  - {f.relative_path}" for f in files)
    template = _TEMPLATES[category]
    text = template.format(file_list=file_list, suffix=_PLAN_ONLY_SUFFIX)
    estimated_tokens = len(text) // 4 + sum(f.size_bytes // 4 for f in files)
    return BurnPrompt(
        category=category,
        text=text,
        estimated_input_tokens=max(1, estimated_tokens),
        target_files=tuple(f.relative_path for f in files),
    )
