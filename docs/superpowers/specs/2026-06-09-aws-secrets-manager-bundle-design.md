# AWS Secrets Manager Bundle Backend

**Status:** Approved
**Date:** 2026-06-09
**Target version:** v0.2.0 (MINOR — new backwards-compatible user-facing feature)
**Author:** Matthew Westwood-Hill

---

## 1. Summary

Add an environment-variable-driven way for konfig's `Secrets` capability to use a
**single designated AWS Secrets Manager secret** for storage and retrieval.

When `KONFIG_AWS_SECRETS_MANAGER=<SECRET_ARN>` is set in the environment, konfig
uses that one AWS secret as a **JSON bundle**: the secret's `SecretString` is a JSON
object, and each konfig secret key is a key within that object. This selection is a
hard override — it wins over an explicit `backend=` argument and over any
`secrets.backend` config-file setting.

This is additive. The existing per-key `AWSSecretsManagerBackend` (selected via the
`secrets.backend: aws_secrets_manager` config setting, one AWS secret per konfig key)
is left untouched.

---

## 2. Motivation

konfig targets cross-platform, cross-deployment applications. In container/cloud
deployments (ECS, EKS, Lambda), the idiomatic pattern is to inject configuration
through the environment and to store an application's secrets together in a single
managed secret provisioned out-of-band (Terraform/CloudFormation/console/CI).

The env-var bundle mode means an operator can point an application at its secrets with
a single environment variable, no code change and no config file, and konfig's
`Secrets` API "just works" against AWS Secrets Manager.

---

## 3. Design decisions (confirmed)

| Decision | Choice |
|----------|--------|
| What the ARN points to | **One** AWS secret whose `SecretString` is a JSON object (a bundle). konfig keys are keys within that JSON. |
| Read vs write | **Read and write.** `set`/`delete` perform read-modify-write on the bundle. |
| Caching | **TTL read cache** (default 300s, configurable) **with write-through**. |
| Write safety | **Re-fetch before write** — each `set`/`delete` re-reads the current bundle from AWS (bypassing the TTL cache) before mutating, then `PutSecretValue`s the whole bundle. |
| Precedence | **Env var wins over everything** — over an explicit `backend=` in code and over `secrets.backend` config. |
| Structure | **New backend class** alongside the existing per-key backend (Approach A). Each class has one data model. |
| Region/account | **Derived from the ARN.** No separate region config needed for this mode. |

---

## 4. Architecture

### 4.1 Selection & precedence

In `Secrets.__init__`, the env var is checked first, before honouring an explicit
`backend=` argument or running auto-detection:

```python
env_arn = os.environ.get("KONFIG_AWS_SECRETS_MANAGER")
if env_arn:                       # hard override — wins over everything
    self._backend = AWSSecretsBundleBackend(arn=env_arn, ttl=resolved_ttl)
elif backend is not None:         # explicit code argument
    self._backend = backend
else:
    self._backend = self._auto_detect_backend()   # settings → keyring → encrypted file
```

`resolved_ttl` is read from `secrets.aws.cache_ttl` when a `Settings` instance is
present, otherwise defaults to `300` seconds. The env var itself carries only the ARN.

### 4.2 New backend — `AWSSecretsBundleBackend`

New file: `src/konfig/secrets/aws_bundle_backend.py`. Implements the existing
`SecretBackend` abstract interface (`get`, `set`, `delete`, `has`, `list_keys`).

Constructor: `AWSSecretsBundleBackend(arn: str, ttl: int = 300)`.

- Imports `boto3` lazily; raises `ImportError` with a `pip install konfig[aws]` hint if
  it is missing (mirrors the existing `AWSSecretsManagerBackend`).
- Parses the ARN to extract the region and configures the boto3 Secrets Manager client
  for that region. All API calls use the full ARN as `SecretId`.

**Data model:** one AWS secret; `SecretString` is a JSON object `{key: value, ...}`.

| Method | Behaviour |
|--------|-----------|
| `get(key)` | Return `bundle.get(key)` from the (TTL-cached) bundle, or `None`. |
| `has(key)` | `key in bundle`. |
| `list_keys()` | `list(bundle.keys())`. |
| `set(key, value)` | Re-fetch bundle from AWS (bypass TTL), set `bundle[key] = value`, `PutSecretValue` whole bundle, update cache. |
| `delete(key)` | Re-fetch bundle from AWS (bypass TTL), drop `key` (no-op if absent), `PutSecretValue` whole bundle, update cache. |

### 4.3 ARN parsing & region

ARN shape: `arn:aws:secretsmanager:<region>:<account-id>:secret:<name>-<suffix>`.

The region is field index 3 (colon-split). It configures the boto3 client. A string
that does not parse as a Secrets Manager ARN with a non-empty region raises a clear
`ValueError`.

### 4.4 Caching & writes

- **TTL read cache** (default 300s, configurable via `secrets.aws.cache_ttl`). The
  first read fetches and parses the bundle; subsequent reads within the TTL use the
  cached parsed dict.
- **Write-through:** after a successful `PutSecretValue`, the in-memory cache is updated
  so reads stay consistent without an extra fetch.
- **Re-fetch before write:** every `set`/`delete` re-reads the current bundle from AWS
  (ignoring the TTL cache) before mutating, shrinking the lost-update window to a single
  API round-trip.
- A `refresh()` method forces a re-fetch on the next read (clears the cache timestamp).

### 4.5 Error handling

| Condition | Behaviour |
|-----------|-----------|
| `boto3` not installed | `ImportError` with `pip install konfig[aws]` hint. |
| Malformed ARN (no parseable region) | `ValueError` with a clear message. |
| `SecretString` is not a JSON object | `ValueError`: "designated secret is not a JSON object". |
| No `SecretString` (binary secret) | `ValueError`: binary secrets are not supported. |
| `ResourceNotFoundException` on read | Treated as an empty bundle: `get`→`None`, `has`→`False`, `list_keys`→`[]`. Allows a freshly-created empty secret to work. |

### 4.6 Config knob

`secrets.aws.cache_ttl` (integer seconds) controls the read-cache TTL when a `Settings`
instance is available. Default `300`.

---

## 5. Packaging & version

- Bump `src/konfig/_version.txt` to `0.2.0`.
- Development happens on `feat/aws-secrets-manager-bundle` (off `main`), integrated via a
  `release/v0.2.0` branch for alpha testing, then merged to `main` and tagged. The
  version on `main` is always a final release; pre-release suffixes (e.g. `0.2.0a1`) live
  only on the release branch.
- The `aws` optional extra (`boto3>=1.34`) already exists in `pyproject.toml`; no new
  dependencies.
- Add a CHANGELOG entry for 0.2.0 (no AI co-authorship references).

---

## 6. Testing

New file: `tests/test_secrets/test_aws_bundle_backend.py`, with `boto3` mocked (no real
AWS calls). Coverage:

- ARN parsing and region extraction (valid and malformed).
- `get` / `has` / `list_keys` against a JSON bundle.
- `set` and `delete` read-modify-write semantics (whole bundle re-put).
- Re-fetch-before-write: a stale cache does not clobber another writer's keys.
- TTL cache hit within the window; re-fetch after expiry.
- Write-through cache update after `set`/`delete`.
- Malformed ARN → `ValueError`; non-JSON `SecretString` → `ValueError`; binary secret →
  `ValueError`.
- `ResourceNotFoundException` → empty-bundle behaviour.
- Missing-`boto3` path → `ImportError`.

Plus a `Secrets`-level test (in or alongside `tests/test_secrets/test_secrets.py`):
`KONFIG_AWS_SECRETS_MANAGER` set in the environment selects the bundle backend even when
an explicit `backend=` is passed.

---

## 7. Documentation

- Update `CLAUDE.md` §2 (Secrets) to document the env-var bundle mode alongside the
  existing per-key backend, including the `KONFIG_AWS_SECRETS_MANAGER` env var, the
  JSON-bundle data model, read/write behaviour, TTL caching, and precedence.
- Update `README` with a short usage example.

---

## 8. Out of scope

- Optimistic locking / version-stage concurrency control (re-fetch-before-write is
  sufficient for a config library).
- Changing or deprecating the existing per-key `AWSSecretsManagerBackend`.
- Secret rotation hooks or AWS-side lifecycle management (the bundle secret is
  provisioned out-of-band).
- Non-AWS cloud secret providers.
