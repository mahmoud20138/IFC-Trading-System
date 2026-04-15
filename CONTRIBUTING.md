# Contributing To IFC Trading System

## Scope

Contributions are welcome for:

- analysis-layer improvements
- dashboard enhancements
- new instruments and broker symbol mappings
- journal analytics and reporting
- risk and execution logic improvements
- documentation and onboarding fixes

## Setup

1. Fork the repository.
2. Create a feature branch.
3. Create your local `config/credentials.py`.
4. Install the Python packages used by the repo.
5. Run `python main.py --mode demo` or `streamlit run dashboard/app.py` to validate changes.

## Guidelines

- Keep changes focused.
- Prefer small, reviewable pull requests.
- Update the README when behavior or setup changes.
- Add or extend tests when modifying analysis, scoring, risk, or execution logic.
- Do not commit credentials, broker secrets, or personal configuration.

## High-Value Contribution Areas

- tighten layer-to-layer wiring and reduce duplicated dashboard logic
- improve MT5 symbol compatibility across brokers
- add missing environment/bootstrap files
- refine page routing so more dashboard modules are reachable from the main app
- improve demo-mode ergonomics and smoke tests

## Pull Requests

Include:

1. what changed
2. why it changed
3. how you tested it
4. any runtime caveats or follow-up work

## Issues

Use GitHub Issues for:

- bugs
- feature requests
- broker/instrument compatibility reports
- documentation problems
