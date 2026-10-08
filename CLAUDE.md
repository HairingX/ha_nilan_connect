# Conventions for this repository

A Home Assistant integration, installed through HACS, for Nilan ventilation units behind a Nilan
gateway, reached over micro_nabto on the local network. The controller itself is modelled by the
`nilan_connect` library; this repository only turns it into Home Assistant devices and entities.
How and why it is built as it is: `docs/design.md`.

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

## Other conventions

- pyright strict must report 0 errors (`pyright`); the configuration is in `pyproject.toml`.
  The workflow scripts are a project of their own: `pyright -p .github/scripts`.
  No `# type: ignore` and no rule turned off: where Home Assistant's own types force a choice,
  take the typed route (`_attr_` values rather than overridden properties).
- Every problem found gets a test that fails without the fix.
- The tests run the real client and the real Nilan models against the library's simulated
  gateway (`nilan_connect.testing`); only the micro_nabto link is simulated. They never reach a
  real controller.
- The email the gateway is paired with is a credential: it is never logged, and never in
  diagnostics.
- Test tools, Home Assistant and the library are pinned in `requirements-test.txt`:
  `pip install -r requirements-test.txt`. They need Python 3.14, as the pinned Home Assistant
  does, on Linux or WSL.
- The pins agree, and tests enforce it: the manifest's requirement is the library version the
  tests run, `hacs.json` requires the Home Assistant version they run, and pymodbus is the
  version Home Assistant's package constraints install.
- A test fails when Home Assistant reports this integration using something deprecated.
- Every point the library has is an entity, or is listed with the reason it is not; a test
  fails for a new point that is neither.
- An existing installation keeps its entities: a unique id is the unit's name and the point's
  key, and a test holds every entity a CTS400 had, with its platform and defaults. Removing or
  moving one is agreed with the user first.
- Translations live in `translations/en.json` and `translations/da.json`, which hold the same
  keys; icons in `icons.json`, by translation key.
- No real IP addresses, hostnames or email addresses in tracked files.

## Keeping up with Home Assistant

Best practice is what Home Assistant and HACS require and recommend now; it moves with every
release. After any change to the integration or to the libraries it uses:

1. Test against the newest Home Assistant release: pin it in `requirements-test.txt` (through
   pytest-homeassistant-custom-component) and `hacs.json`, then run the tests, pyright and
   hassfest. A deprecation Home Assistant reports fails the tests.
2. Read the Integration Quality Scale rules and HACS's publishing requirements again, and bring
   `quality_scale.yaml` up to date; a test checks it lists every rule, with a reason for each
   exemption and each rule not yet met.
3. Read the Home Assistant developer blog since the last check for changes to what integrations
   do.
4. Run the live test against a real controller.

## Releasing

**The manifest in the repository always says `0.0.0`, and the draft release is never published
by hand.** HACS installs the zip a release carries (`zip_release` and `filename` in `hacs.json`),
and only Release builds it: the manifest in the zip says the release's version.

1. Merge pull requests into `main`. Release Drafter keeps a draft release proposing the next
   version: a minor bump for the label `breaking-change` or `minor`, a patch otherwise.
   **A new major version is never worked out**, as a label placed wrongly must not release one;
   type it into Release as the override.
2. Run the **Release** workflow from the Actions tab, on `main`, and choose **release
   candidate** or **final release**. It works out the version: the next release candidate of the
   open series (`0.2.0rc1` -> `0.2.0rc2`), or the final release that ends it (`0.2.0`); a draft
   naming a higher version starts a new series. Type a version only for a new major, or to
   override one worked out wrongly: canonical PEP 440, of the kind chosen.

Release refuses a version with no pull request merged since the release before it - for a
final release, the final release before it.

Release refuses any version not higher than every version tagged. It runs the tests and the
hassfest and HACS validation on the commit it releases, builds the zip from that commit with the
manifest's version set and checks it, tags that commit - nothing is pushed to `main` - and
publishes the GitHub release with the zip, marked as a pre-release where it is one; HACS offers a
pre-release only to those who ask for them.

A release candidate's notes are written by GitHub from the pull requests merged since the
previous release candidate or final release, grouped by label as `.github/release.yml` says. A
final release's notes are the draft's: edit the draft - it lists what was merged since the last
final release - and run Release before anything else is merged, as a merge rewrites the draft.
Without a draft, GitHub writes them from the pull requests since the previous final release. Test builds are not counted as releases.

The library comes from PyPI at the version the manifest pins. **Release the library first**, then
pin its version here in the manifest and `requirements-test.txt`.

Actions are referred to by their major version where they publish one; Dependabot proposes a new
major, and updates to the test tools, as pull requests.

## Testing a branch on a real Home Assistant

HACS installs only releases, pre-releases and the default branch. To try a development branch
on a real Home Assistant - discovery, for one, needs a real network - run the **Test build**
workflow from the Actions tab on that branch:

1. It tests and validates the branch's commit, then publishes it as a pre-release such as
   `v0.1.0b3`: the next release's version with the first free `b<n>`. The branch's commit is
   tagged; the version and the libraries are set only in the zip the pre-release carries.
2. Where modbus_event_connect or nilan_connect has a branch of the same name, the test
   build requires that branch's current commit, from GitHub; otherwise the version the manifest
   pins. Home Assistant then checks that requirement at every start, so it must reach GitHub.
3. In Home Assistant, switch pre-releases on for this repository in HACS, and install the test
   build. Switch them off and install the latest release to go back.

A new test build of a branch replaces its previous one, and closing the branch's pull request or
deleting the branch removes them. Development branches are tested the same way in CI: with the
libraries' branch of the same name, where they have one.

## Branches and pull requests

- Every change goes through a branch and a pull request: `main` takes no push. A ruleset
  enforces it; its only bypass is the owner's, and only for merging a pull request. A change
  to what a user gets - the integration's code or documentation - comes with its tests.
- Name every branch by the kind of change, as the release draft's labels follow the name:
  `feature/<what>` is labelled `feature request`, `fix/<what>` is labelled `bug`,
  `docs/<what>` is labelled `documentation`, and `chore/<what>` - CI, tooling, anything that
  stays in the repository - is labelled `chore`. The release notes list features and fixes;
  documentation, chores and Dependabot's `dependencies` are left out. A change to what a user
  installs, such as a new library pin, is a `fix/` or a `feature/`, never a `chore/`.
- A pull request's text describes only its own change: what it does and how it was tested. Never
  releases to come, merge order, or other repositories.
- Put `breaking-change` on a pull request that breaks the API - a `feature/` or `fix/` one, as a
  chore is left out of the notes - and `minor` on one that needs a minor bump; both give a minor
  bump, and a patch is the default. No label gives a major.
