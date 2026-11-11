# WENGOLD durable workers and signed engineering review

## Status and scope

- Local durable SQLite queue supports **multiple worker processes on one shared
  filesystem**, not distributed cross-host orchestration. A transaction leases
  one job at a time, expires lost leases, and fences stale workers by attempt.
- Syntax, formal and syntax-to-formal are bounded tasks. Unknown and tool failures
  are never counted as proof. Snapshots are frozen at submission.
- A PyQt6 **Workers** tab submits and monitors durable jobs.
- Review of **legacy StudioJobs** can be backed by Ed25519 public keys. This is
  a cryptographic signature check, not organizational identity verification or
  production tapeout authorization.
- Ledger anchors can be exported to an administrator-controlled **external
  directory**. Use separately protected/immutable storage for independence.
  This is not a public timestamp authority and does not upload automatically.

## Run several independent local workers

From WENGOLD's project directory:

\`\`\`bash
python3 -m pip install -e '.[native,formal,slang,security]'
wengold desktop --native ./rtl
# In two separate terminals, both against the SAME project root:
python3 -m wengold.studio_durable ./rtl --worker
python3 -m wengold.studio_durable ./rtl --worker
\`\`\`

The queue is written to \`.wengold-jobs.sqlite3\` under the project. Workers
take transactionally exclusive claims. Completed jobs survive shutdown;
uncommitted work is retried only after lease expiry and up to 3 total attempts.
The worker has an explicit job allowlist and does not execute arbitrary commands.
Avoid NFS for SQLite shared writes; use a server-side broker/DB for remote hosts.

## Enroll a verified reviewer (administrative setup)

The administrator must verify identities out of band and place each reviewer
public key on a secured, independently administered directory. Example:

\`\`\`bash
mkdir -p ~/.config/wengold/trusted-reviewers
openssl genpkey -algorithm Ed25519 -out ~/reviewer-private.pem
openssl pkey -in ~/reviewer-private.pem -pubout \
    -out ~/.config/wengold/trusted-reviewers/reviewer.pub
chmod 600 ~/reviewer-private.pem
export WENGOLD_TRUSTED_REVIEWERS_DIR="$HOME/.config/wengold/trusted-reviewers"
\`\`\`

Keep private keys outside the project, backed by OS permissions or hardware
key storage; do not commit either keys or passwords. This quickstart has one
self-enrolled key and is NOT a corporate identity-enrollment policy.

To sign a review, export the complete job JSON from the Jobs evidence pane
to a local file (\`job.json\`), then:

\`\`\`bash
python3 -m wengold.studio_attest sign --job job.json \
  --reviewer reviewer --decision accept \
  --private-key ~/reviewer-private.pem
\`\`\`

Paste the resulting base64 signature into the native **Review Signature** field,
enter the exact reviewer ID, and choose **Accept proof**. Acceptance is possible
only when the source fingerprint still matches, a formal result actually reports
proof, the ledger audit succeeds, and the signature verifies against a trusted key.

The old \`WENGOLD_REVIEW_KEY_SHA256\` mechanism remains for backwards compatibility
if \`WENGOLD_TRUSTED_REVIEWERS_DIR\` is *not* set. It is not identity authentication.

## Export and check a separately retained ledger anchor

\`\`\`bash
mkdir -p /mnt/independent-evidence-store
python3 -m wengold.studio_attest anchor \
  --ledger ./rtl/.wengold-studio-ledger.jsonl \
  --external-dir /mnt/independent-evidence-store
python3 -m wengold.studio_attest verify \
  --ledger ./rtl/.wengold-studio-ledger.jsonl \
  --anchor /mnt/independent-evidence-store/wengold-anchor-EXAMPLE.json
\`\`\`

The anchor filename is returned by the export command (replace EXAMPLE with
the actual path). The stored root hash verifies the original prefix even
when new ledger entries appear. Independent retention, permissions, time
attestation, backup and reviewer identity governance remain site obligations.

## Validation

\`\`\`bash
QT_QPA_PLATFORM=offscreen python3 -m pytest -q \
  tests/test_studio_durable.py tests/test_studio_milestone.py \
  tests/test_native_studio.py
\`\`\`

The dedicated Linux native-smoke workflow includes these focused tests.
The broader OS matrix has separate lifecycle and runtime checks.
