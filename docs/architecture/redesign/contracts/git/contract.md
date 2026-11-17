# Git domain — design-stage reference

The implemented R3.1 read-only API and its canonical contract live in
[`apatch_lib/git/contract.md`](../../../../../apatch_lib/git/contract.md).

Later R3 slices will move the subprocess command runner, branch/ref guards,
confirmation boundary and authorized local mutation adapter behind a reviewed
Git API. Those changes are not implemented by R3.1.

The R3.1 read-only operations retain the existing `gitutil` runtime adapter
for their actual commands; this is a documented transitional dependency.
