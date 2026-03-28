# External Tools Scan Log

## 2026-03-28 -- Security scan of S:/q/stockfish-instrumentation

### bandit 1.9.2
- Start: 2026-03-28 16:58:06 UTC
- Status: COMPLETED
- Files scanned: 849 lines of code, 0 skipped
- Findings: 3 Low-severity issues (all in shared/bench_runner.py)
  - B404: subprocess module import
  - B603: subprocess.Popen without shell=True check
  - B101: assert used (removed in optimized bytecode)
- Output: scratchpad/bandit-report.txt

### semgrep (via semgrep-runner.py)
- Start: 2026-03-28
- Status: COMPLETED
- Findings: 0 findings
- Note: semgrep-raw.txt shows parse error (empty/malformed raw output), semgrep-report.txt is empty array []
- Output: scratchpad/semgrep-report.txt, scratchpad/semgrep-raw.txt

### gitleaks 8.30.0
- Start: 2026-03-28
- Status: COMPLETED
- Findings: 0 secrets detected (filesystem scan and git history scan both clean)
- Output: scratchpad/gitleaks-report.json, scratchpad/gitleaks-git-report.json

### trivy 0.69.3 (fs)
- Start: 2026-03-28 18:58:57 +02:00
- Status: COMPLETED
- Findings: 0 vulnerabilities, 0 secrets, 0 misconfigurations detected
- Output: scratchpad/trivy-report.json

### Snyk 1.1301.2 (code test)
- Start: 2026-03-28
- Status: COMPLETED
- Findings: 6 MEDIUM, 0 HIGH, 0 LOW -- all Path Traversal (unsanitized CLI args into file paths)
  - aggregate_nmp_perpos.py line 67: arg into pathlib.Path (read)
  - compute_nmp_freq_table.py line 82: arg into pathlib.Path (read)
  - run_nmp_perpos.py line 65: arg into pathlib.Path (read)
  - run_delta_sweep.py line 194: arg into open() (write)
  - run_nmp_perpos.py line 75: arg into open() (write)
  - run_occupancy_sweep.py line 167: arg into open() (write)
- Output: scratchpad/snyk-results.txt
