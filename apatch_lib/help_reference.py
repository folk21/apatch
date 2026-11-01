"""User-facing CLI reference kept separate from request parsing and validation."""

from textwrap import dedent

from .core.actions import ACTION_CODES


HELP_EPILOG = dedent("""
    QUICK START
      Run apatch from the ROOT OF THE TARGET GIT REPOSITORY, not from the
      installed apatch tool directory. The ZIP must contain
      <repository>/.apatch/params.json and <repository>/source files.

      apatch.sh project-PATCH-feature opSeq=APL,BRN,CHK,STS skipApproves=true
      apatch.sh opSeq=CMT,PSH,PR,MRG,SYN,STS skipApproves=true

    WORKFLOW STAGES
      APL  Apply a selected ZIP in the target working tree.
      BRN  Create or safely select the feature branch for the applied patch.
      FMT  Run project-defined MUTATING formatters; optional, before CHK.
      CHK  Run project-defined READ-ONLY checks; required before safe commit.
      REV  Independent script/LLM code review of the checked bytes; optional.
      CMT  Commit confirmed changes without pushing (LOOSE mode).
      PSH  Push the commit; PR creates the pull request.
      MRG  Merge after GitHub checks; SYN synchronizes the local base branch.
      STS  Inspect recorded local workflow state (remote status not queried).
      AUD  Audit local patch history; verifyRemote=true enables GitHub reads.

      Common sequence: APL,BRN,FMT,CHK,REV,CMT,PSH,PR,MRG,SYN,STS.
      Omit FMT if format_commands are absent. Omit REV unless requested or
      review_required=true. STS is safe to run independently.

    CONFIGURE PROJECT CHECKS AND FORMATTERS
      Create <target-repository>/.apatch/config.yaml with schema_version: 1.
      The checks list is REQUIRED. Examples (adapt paths to your project):

        schema_version: 1
        checks:
          - ["./run-tests.sh"]
          - ["dart", "format", "--output=none", "--set-exit-if-changed", "app/lib", "app/test"]
        format_commands:
          - ["dart", "format", "app/lib", "app/test"]
          - ["cargo", "fmt", "--manifest-path", "core/Cargo.toml", "--all"]
        check_timeout_seconds: 900
        check_idle_timeout_seconds: 30

      Run only installed formatters relevant to your stack; remove commands
      for tools that are not used. All commands are argv arrays, not shell
      strings: no pipes, redirects, glob expansion, or variable interpolation.
      To run a shell pipeline, put it in a project-owned script and list that
      script as one command. Commands execute from the TARGET repository root.

      FMT changes source files and invalidates old CHK/REV evidence. CHK MUST
      NOT change files. If run-tests.sh formats source, split formatting into
      a separate script, then call FMT before CHK. A failed formatter or check
      preserves edits but blocks later publication until corrected.

      Example when the project already has ./run-checks.sh --prepare:
        format_commands:
          - ["./run-checks.sh", "--prepare"]
        checks:
          - ["./run-tests.sh"]

    OPTIONAL PREPARATION IN GUARDED MACROS
      prepare_checks: [["./prepare-project.sh"]]
      check_worktree_policy: stop   # or recheck_once
      prepare_checks is NOT the FMT operation. It applies only to guarded
      APPLY_PATCH_CHECK, MERGE, and RUN_ALL macros with planned checks.
      Direct CHK remains strictly read-only, even with recheck_once configured.

    OPTIONAL CODE REVIEW (REV)
      Config keys and examples in .apatch/config.yaml:

        review_required: false
        review_timeout_seconds: 180
        review_max_bytes: 131072
        reviewers:
          - id: static
            kind: script
            command: ["./scripts/review.sh", "{diff_file}"]
          - id: gemini
            kind: llm
            model: gemini-2.5-pro
            command: ["gemini", "--model", "{model}", "--output-format", "json", "-p", "Review the supplied diff and return a JSON verdict."]

      Review is OPTIONAL by default. Set review_required: true to block commits
      unless all configured reviewers pass on the current checked snapshot.
      A script reviewer receives the diff on stdin and must exit 0 to pass.
      A model reviewer must return a JSON verdict: PASS, CHANGES_REQUIRED, or
      ESCALATE. The configured external CLI owns authentication and billing.
      Never send private code or secrets to an untrusted external model.

    CONFIGURE GLOBAL DEFAULTS
      The installed apatch/apatch.conf uses INI syntax, not YAML. For example:

        [apatch]
        downloads_dir = ~/Downloads
        base_branch = main
        github_timeout_seconds = 30
        github_ci_wait_seconds = 300
        check_timeout_seconds = 900
        check_idle_timeout_seconds = 30

      Project .apatch/config.yaml can override supported global options.
      Never put secrets or credentials in checked-in configuration files.

    COMMON COMMANDS AND RESUME
      apatch.sh project-PATCH-new op=APL skipApproves=true
      apatch.sh project-PATCH-new op=3 skipApproves=true
      apatch.sh op=BRN skipApproves=true
      apatch.sh opSeq=FMT,CHK,STS skipApproves=true
      apatch.sh opSeq=CHK,REV,CMT,STS skipApproves=true
      apatch.sh op=STS
      apatch.sh op=AUD verifyRemote=false
      apatch.sh info=PROGRESS
      apatch.sh project-PATCH-new goal=CHECKED planOnly=true
      apatch.sh goal=MERGED skipApproves=true
      apatch.sh project-PATCH-new op=RUN_ALL skipApproves=true

      Named macros: APPLY_PATCH (APL+BRN), APPLY_PATCH_CHECK (through CHK),
      MERGE (CMT through SYN), RUN_ALL (full guarded workflow).
      Goals: CHECKED, COMMITTED, PUSHED, PR_CREATED, MERGED.
      Use handoffSeq=zip1.zip,zip2.zip for multiple explicit APL entries.
      Use followup=true only when intentionally applying a repair ZIP to an
      unfinished matching LOOSE feature session. featureBranch=feature/new
      can safely reassign a pending ZIP before BRN where allowed.

      If CHK or REV fails: correct the reported files, run STS, then resume
      from the failed operation. Do not replay APL/BRN on already applied ZIPs
      unless explicitly recovering their state. A previously synchronized ZIP
      with a verified, complete APL-to-SYN opSeq returns ALREADY_COMPLETED and
      displays terminal STS without replaying actions. An incomplete cycle,
      dirty base, or changed remote is not treated as complete.
      If an old params.json lacks a verified ZIP digest, STS reports recorded
      state without trusting that cache. Select the original ZIP explicitly
      to resume: project-PATCH-name opSeq=BRN,CHK,STS skipApproves=true.
      Invalid bounded cache files are preserved in .apatch/backups/ before
      replacement. A symlinked cache or backup directory blocks new APL.
      skipApproves=true disables
      prompts, NOT Git, ZIP, or repository safety checks. FORCE is NOT a
      force-push option. Remote GitHub checks remain separate from local CHK.

    VERIFIED ZIP PRODUCTION (SEPARATE FROM CONSUMER OPERATIONS)
      python3 /path/to/apatch/apatch_preflight.py --project . --prepare
      python3 /path/to/apatch/apatch_pack.py --help
      Use apatch_pack.py for source checks and validated ZIP creation before
      applying the ZIP with APL in the destination repository.

    DOCUMENTATION
      README.md, docs/INSTALLATION.md, docs/USAGE.md,
      docs/DEVELOPMENT.md, docs/SECURITY.md, docs/ARCHITECTURE.md.
""").strip() + "\n\nAction codes: " + ", ".join(
    f"{number}={name}" for number, name in enumerate(ACTION_CODES))


PACK_HELP_EPILOG = dedent("""
    PURPOSE
      This is the PRODUCER-side command. Run it in the source Git checkout
      before delivering a patch ZIP. The normal apatch APL/CHK workflow is
      used later in the DESTINATION repository.

    FIRST REVIEW THE FILE MANIFEST (READ-ONLY)
      python3 /path/to/apatch/apatch_pack.py --project . --discover
      python3 /path/to/apatch/apatch_pack.py --project . --discover --json

      Discovery reports modified, new, renamed, and deleted Git paths and
      prints suggested --include and --delete arguments. No files are written,
      no formatters/checks run, and no ZIP is created. Untracked files are
      shown separately: inspect them for secrets and unwanted content.
      Discovery is NOT approval to include any path in an archive.

    THEN BUILD AN EXPLICIT ZIP
      python3 /path/to/apatch/apatch_pack.py \\
        --project . \\
        --output /path/outside/source/project-PATCH-feature.zip \\
        --branch feature/example \\
        --message "feat: implement example" \\
        --include app/lib/example.dart \\
        --include app/test/example_test.dart \\
        --prepare

      Repeat --include for each new/changed source file, and --delete for
      each removed tracked file. All Git changes must be accounted for; use a
      dedicated source worktree if unrelated untracked files are present.
      Output must be outside source Git, must be a .zip basename, and must
      not exist. Destination feature branch must start with feature/.

    CONFIGURE FORMATTERS AND CHECKS
      Create <source-repository>/.apatch/config.yaml, for example:

        schema_version: 1
        format_commands:
          - ["./run-checks.sh", "--prepare"]
        checks:
          - ["./run-tests.sh"]

      --prepare explicitly runs MUTATING format_commands, followed by
      READ-ONLY checks. Without --prepare, only checks run. Missing tools,
      failed formatters, nonzero checks, Git whitespace errors, and changes
      caused by read-only checks prevent publication. Commands are argv lists
      (no implicit shell expansion). Use the real Dart/Rust formatters for
      your project. Do not list a mutating formatter under checks.

    SOURCE CONSISTENCY AND FAILURES
      The packer always invokes preflight; a previous standalone preflight
      success is not reused. ZIP members must match the source bytes and
      executable modes checked during preflight. Branch/HEAD/index/worktree
      drift stops packaging. Existing ZIP files are never overwritten.
      --base-commit optionally binds the handoff to an exact DESTINATION
      commit SHA. Never guess it from the producer checkout HEAD.
      --json writes one result to stdout; command logs go to stderr.

    RELATED COMMANDS
      apatch_preflight.py --help  Standalone source verification/formatting.
      apatch.sh --help            Full consumer workflow/configuration guide.
      docs/DEVELOPMENT.md        Producer details and security boundaries.
""").strip()


PREFLIGHT_HELP_EPILOG = dedent("""
    SOURCE PREFLIGHT BEFORE PATCH CREATION
      python3 /path/to/apatch/apatch_preflight.py --project . --prepare
      python3 /path/to/apatch/apatch_preflight.py --project . --json

      Run from the SOURCE Git repository root. This command does not build
      a ZIP, apply a patch, commit, stage, or publish anything. It requires
      <project>/.apatch/config.yaml with schema_version: 1 and checks.

    PROJECT CONFIGURATION EXAMPLE
      schema_version: 1
      format_commands:
        - ["./run-checks.sh", "--prepare"]
      checks:
        - ["./run-tests.sh"]
        - ["dart", "format", "--output=none", "--set-exit-if-changed", "app/lib", "app/test"]
      check_timeout_seconds: 900
      check_idle_timeout_seconds: 30

      --prepare is explicitly MUTATING: it runs configured format_commands
      before canonical checks. Omit it for READ-ONLY verification. A missing
      format_commands list makes --prepare fail. The checks MUST NOT change
      tracked or untracked source files or the Git index. Git whitespace
      checks also fail closed. Missing tools, nonzero exits, and timeouts
      return nonzero; successful checks identify the current Git snapshot.

    BEFORE DELIVERING A ZIP
      The source may change after preflight. For a ZIP tied to the exact
      verified bytes, use apatch_pack.py: it reruns preflight and rejects
      source drift before publishing the archive. CHK remains mandatory in
      the destination repository after ZIP application.
""").strip()
