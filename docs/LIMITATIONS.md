# Limitations and release eligibility

This is a production-contract preview, not a demonstrated high-recall reviewer.

- Local-model reasoning can miss simple defects. A completed assessment is not
  a guarantee of correct reasoning. The live diagnostic traces preserve misses.
- Static verification is not BASE/HEAD execution attribution. Existing test
  failures block approval eligibility but do not automatically establish a regression.
- Local `--execute-tests` uses a worktree, path restrictions, a timeout, and a
  filtered environment. It is not an OS security sandbox. Untrusted code can
  still access files available to the process. Only use it for trusted code.
  Execution is disabled in GitHub Actions. A credential-free container/service
  runner remains future work before arbitrary untrusted execution can be enabled.
- Graph indexing is optional and disabled by default. Missing/stale graphs are
  unavailable context, not successful indexing. Multi-file Python analysis with
  missing graph context is partial. Broader language/context classification needs
  further validation; a graph does not itself establish evidence completeness.
- Rules cover a narrow set of structural patterns. Their static facts do not
  demonstrate general defect recall across languages or projects.
- Duplicate protection uses publisher identity, exact revisions, markers,
  local locking, and workflow concurrency. Cross-machine races remain possible.
- Publication is checked immediately before submission, but a PR may still move
  during the network request. The submitted review remains bound to its reviewed commit.
- GitHub publishing needs valid credentials and repository permissions. GitHub
  can prohibit an author from approving or requesting changes on their own PR.
- Fork automation, self-hosted arbitrary execution, custom OpenAI-compatible
  providers, first-run wizard flows, and Linux installation are not claimed
  live-validated solely from local Windows checks.
- Hosted CI checks are configured but not executed by editing workflow files locally.
- Clean real PR labels, a sufficiently large adjudicated corpus, controlled
  validation gains, and a fresh held-out release run remain requirements for P1.
  Synthetic smoke cases cannot substitute for them.
- A dirty working tree cannot qualify as a frozen reviewer release. Build an
  approved immutable revision, pin dependencies, then run the release gate.

Historical results in SHIP_VALIDATION.md and VALIDATION_V1.md are evidence for
their recorded revisions only, not evidence for this preview.
