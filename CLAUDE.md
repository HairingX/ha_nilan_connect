# Conventions for this repository

A Home Assistant integration, installed through HACS, for Nilan ventilation units behind a Nilan
gateway, reached over micro_nabto on the local network. The controller itself is modelled by the
`nilan_connect` library; this repository only turns it into Home Assistant devices and entities.
How and why it is built as it is: `docs/design.md`.

## This integration

- The tests run the real client and the real Nilan models against the library's simulated
  gateway (`nilan_connect.testing`); only the micro_nabto link is simulated. They never reach a
  real controller.
- The email the gateway is paired with is a credential: it is never logged, and never in
  diagnostics.
- pymodbus is the version Home Assistant's package constraints install; a test checks it.
- Every point the library has is an entity, or is listed with the reason it is not; a test
  fails for a new point that is neither.
- An existing installation keeps its entities: a unique id is the unit's name and the point's
  key, and a test holds every entity a CTS400 had, with its platform and defaults. Removing or
  moving one is agreed with the user first.
- Discovery needs a real network: try it with a test build.
- The libraries developed alongside it are `modbus_event_connect` and `nilan_connect`, in that
  order, listed in `pyproject.toml` for test builds and CI.

<!-- BEGIN ha_integration_workflows: shared by every integration; edit it there -->
## Shared by every integration

This section, the workflows and the release tools are the same in every Home Assistant
integration of the owner. They come from `HairingX/ha_integration_workflows`: the workflows in
`.github/` are copies of its template, which call its reusable workflows and actions at `@v1`,
and this section is a copy of its `template/CLAUDE.md`. The tests check that the copies agree;
a change to any of them is made there, released, and synced into every repository with its
`tools/template.py sync`. What is this repository's own is above this section.

## Comments and docstrings

Based on PEP 8 (Comments), PEP 257 (Docstring Conventions) and the Google Python Style Guide
(3.8 Comments and Docstrings).

**Docstrings describe the unit's own contract, and nothing else.**
- Every public module, class, function and method has one.
- The first line is a one-sentence summary. Add more only when a caller needs it: arguments,
  return value, exceptions raised, side effects, invariants.
- Use Google style sections (`Args:`, `Returns:`, `Raises:`) only when they say something the
  signature and type hints do not. Never repeat types; the hints carry them.
- Describe what the unit does, not who calls it, how other classes use its data, or where its
  result ends up. That knowledge belongs to those other units and goes stale here.

**Comments explain why, never what.**
- Write one only where the code cannot say it: a protocol quirk, a non-obvious constraint, the
  reason for an order of operations.
- No history: no "used to", "previously", "the old code", "this was a bug". Version control
  holds history; a regression test's name holds the reason it exists.
- No references to other files, classes, line numbers or design-document sections. They rot the
  moment the other side changes.
- No commented-out code. No TODO without an issue reference.

**Keep them short.** A comment longer than a few lines is design rationale; it belongs in
`docs/`, where it can cover several modules at once.

**Tests.** The test name states the behaviour. Add a docstring only when the reason is not
obvious from the name - one or two lines, no narrative.

## Conventions

- All documentation, comments and commit messages are in English.
- pyright strict must report 0 errors (`pyright`); the configuration is in `pyproject.toml`.
  No `# type: ignore` and no rule turned off: where Home Assistant's own types force a choice,
  take the typed route (`_attr_` values rather than overridden properties).
- The tests are pytest with pytest-homeassistant-custom-component, in `tests/`, and cover every
  line of the integration; the build fails below 100%. Tests that need a real device are marked
  `live`, skip themselves without one, and never run in CI.
- A repository on its way to this standard says so under `[tool.ha-integration-workflows]` in
  `pyproject.toml`: `transition` says why, and `coverage` the percentage its tests must reach
  meanwhile; pyright, still strict, may leave the files listed in `[tool.pyright] ignore`
  unchecked. Every run warns while it lasts. Each pull request raises the coverage and takes
  files off the list, never the reverse, until the transition is removed.
- Every problem found gets a test that fails without the fix.
- A test fails when Home Assistant reports this integration using something deprecated.
- Test tools, Home Assistant and the libraries are pinned in `requirements-test.txt`:
  `pip install -r requirements-test.txt`. They need Python 3.14, as the pinned Home Assistant
  does, on Linux or WSL.
- The requirements follow hassfest's rules for a custom integration, which shares Home
  Assistant's Python environment, and the tests enforce them: a package Home Assistant itself
  installs is not listed; one Home Assistant's own integrations pin is required at a minimum
  version that admits theirs, and the tests run Home Assistant's version; any other is pinned
  with `==`, and the tests run that version. `requirements-test.txt` pins what the tests run.
  `hacs.json` requires the Home Assistant version the tests run, and names the zip after the
  domain.
- `quality_scale.yaml` states every rule of the Integration Quality Scale, with a reason for each
  exemption and each rule not yet met; the tests check it.
- Translations live in `translations/en.json` and `translations/da.json`, which hold the same
  keys, as the tests check; icons in `icons.json`, by translation key.
- No real IP addresses, hostnames, serial numbers or email addresses in tracked files. Examples
  use the documentation ranges, such as 192.0.2.0/24.

## Keeping up with Home Assistant

Best practice is what Home Assistant and HACS require and recommend now; it moves with every
release. After any change to the integration or to the libraries it uses:

1. Test against the newest Home Assistant release: pin it in `requirements-test.txt` (through
   pytest-homeassistant-custom-component) and `hacs.json`, then run the tests, pyright and
   hassfest. A deprecation Home Assistant reports fails the tests.
2. Read the Integration Quality Scale rules and HACS's publishing requirements again, and bring
   `quality_scale.yaml` up to date.
3. Read the Home Assistant developer blog since the last check for changes to what integrations
   do.
4. Run the live tests against a real device, where the integration has them.

## Releasing

**The manifest in the repository always says `0.0.0`, and the draft release is never published
by hand.** HACS installs the zip a release carries (`zip_release` and `filename` in `hacs.json`),
and only Release builds it: it writes the release's version into the manifest on the runner,
and refuses a zip whose manifest says anything else. Nothing is committed by a release: the
tested commit is tagged, and the version exists only in the tag and the zip.

1. Merge pull requests into `main`. Release Drafter keeps a draft release proposing the next
   version: a minor bump for the label `breaking-change` or `minor`, a patch otherwise.
   **A new major version is never worked out**, as a label placed wrongly must not release one;
   type it into Release as the override.
2. Wait until the Release Drafter run on `main` has finished. Release refuses a draft that is not
   up to date with `main`.
3. Show the maintainer the draft's notes and its version, and get explicit approval before
   running Release.
4. Run the **Release** workflow from the Actions tab, on `main`, and choose **release
   candidate** or **final release**. It works out the version: the next release candidate of the
   open series (`0.2.0rc1` -> `0.2.0rc2`), or the final release that ends it (`0.2.0`); a draft
   naming a higher version starts a new series. Type a version only for a new major, or to
   override one worked out wrongly: canonical PEP 440, of the kind chosen.

Release refuses any version not higher than every version released, and a version with no pull
request merged since the release before it - for a final release, the final release before it.
It runs the tests and the hassfest and HACS validation on the exact commit it releases, builds
the zip from that commit with the manifest's version set and checks it, tags that commit, and
publishes the GitHub release with the zip, marked as a pre-release where it is one; HACS offers
a pre-release only to those who switch beta versions on, and then the newest one.

A release candidate's notes are written by GitHub from the pull requests merged since the
previous release candidate or final release, grouped by label as `.github/release.yml` says, and
the draft is kept. A final release's notes are the draft's, and the final release deletes the
draft. To change what a release says, change the pull requests: the title is the line, the
labels decide the section.

If publishing fails part-way, **Re-run failed jobs** resumes it: it accepts the tag it pushed on
the same commit, removes a draft an interrupted upload left behind, and uploads the zip to the
release it already created. **Re-run all jobs** is refused once the version is tagged.

The libraries come from PyPI at the version the manifest pins. **Release a library first**, then
pin its version here in the manifest and `requirements-test.txt`.

Actions are referred to by their major version where they publish one; Dependabot proposes a new
major, and updates to the test tools, as pull requests.

## Testing a branch on a real Home Assistant

HACS installs only releases, pre-releases and the default branch. To try a development branch
on a real Home Assistant, run the **Test build** workflow from the Actions tab on that branch:

1. It tests and validates the branch's commit, then publishes it as a pre-release such as
   `v0.1.0b3`: the next release's version - the draft's, or the patch after the last release
   when there is no draft - with the first free `b<n>`. The branch's commit is tagged; the
   version and the libraries are set only in the zip the pre-release carries.
2. Where a library listed under `[tool.ha-integration-workflows] libraries` in `pyproject.toml`
   has a branch of the same name, the test build requires that branch's current commit, from
   GitHub; otherwise the version the manifest pins. Home Assistant then checks that requirement
   at every start, so it must reach GitHub.
3. In Home Assistant, switch beta versions on for this repository in HACS, and install the test
   build. Switch them off and install the latest release to go back.

A new test build of a branch replaces its previous one, and closing the branch's pull request or
deleting the branch removes them. Test builds never count as releases. Development branches are
tested the same way in CI: with the libraries' branch of the same name, where they have one, in
place of their pin in `requirements-test.txt`. The pin checks are skipped then, as a library
built from a branch is no release; instead, the check "Libraries released and pinned" fails until
the library is released, pinned here and its branch deleted.

## Branches and pull requests

- Every change goes through a branch and a pull request: `main` takes no push. The ruleset in
  `.github/rulesets/main.json` enforces it, with the checks "Tests and type check", "Hassfest",
  "HACS" and "Libraries released and pinned" required; its only bypass is the owner's, and only
  for merging a pull request. A change to what a user gets - the integration's code or
  documentation - comes with its tests.
- Name every branch by the kind of change, as the release draft's labels follow the name;
  `.github/rulesets/branch-names.json` refuses any other name. `feature/<what>` is labelled
  `feature request`, `fix/<what>` is labelled `bug`, `docs/<what>` is labelled `documentation`,
  and `chore/<what>` - CI, tooling, anything that stays in the repository - is labelled `chore`.
  The release notes list features and fixes; documentation, chores and Dependabot's
  `dependencies` are left out. A change to what a user installs, such as a new library pin, is a
  `fix/` or a `feature/`, never a `chore/`.
- A pull request's text describes only its own change: what it does and how it was tested. Never
  releases to come, merge order, or other repositories.
- Put `breaking-change` on a pull request that breaks the API - a `feature/` or `fix/` one, as a
  chore is left out of the notes - and `minor` on one that needs a minor bump; both give a minor
  bump, and a patch is the default. No label gives a major.
<!-- END ha_integration_workflows -->
