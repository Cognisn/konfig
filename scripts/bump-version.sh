#!/usr/bin/env bash
# Single-source version management. version.txt is the source of truth.
#
# Usage:
#   scripts/bump-version.sh           Print the current version.
#   scripts/bump-version.sh 0.2.0     Set version.txt, propagate to manifests,
#                                      and roll CHANGELOG.md.
#   scripts/bump-version.sh 0.2.0a1   Pre-release (aN, bN or rcN): set
#                                      version.txt and propagate, but leave
#                                      CHANGELOG.md alone for the final roll.
set -euo pipefail

# Locate the version file. In this repository the source of truth is
# src/konfig/_version.txt (read dynamically by hatchling via pyproject.toml).
version_file=$(find src -maxdepth 2 \( -name _version.txt -o -name version.txt \) -print -quit 2>/dev/null || true)
if [ -z "${version_file}" ]; then
  echo "_version.txt not found under src/*/" >&2
  exit 1
fi

current=$(tr -d '[:space:]' < "${version_file}")

if [ "$#" -eq 0 ]; then
  echo "${current}"
  exit 0
fi

new="$1"
today=$(date +%F)

# MAJOR.MINOR.PATCH with an optional PEP 440 pre-release suffix (aN, bN, rcN).
# Checked before anything is written.
version_re='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)((a|b|rc)(0|[1-9][0-9]*))?$'
if ! [[ "${new}" =~ ${version_re} ]]; then
  echo "invalid version '${new}': expected MAJOR.MINOR.PATCH with an optional aN, bN or rcN suffix (for example 0.5.0 or 0.5.0rc1)" >&2
  exit 1
fi
prerelease="${BASH_REMATCH[4]}"

printf '%s\n' "${new}" > "${version_file}"
echo "version.txt: ${current} -> ${new}"

# Propagate to manifests that store the version literally.
if [ -f package.json ]; then
  if command -v npm >/dev/null 2>&1; then
    npm version "${new}" --no-git-tag-version --allow-same-version >/dev/null
  else
    node -e "const f='package.json';const p=require('./'+f);p.version=process.argv[1];require('fs').writeFileSync(f,JSON.stringify(p,null,2)+'\n')" "${new}"
  fi
  echo "package.json: ${new}"
fi

# Python projects read the version dynamically from version.txt (see the
# pyproject configuration applied during onboarding), so nothing to propagate.

# Roll CHANGELOG.md: promote [Unreleased] to a dated section for this version
# and open a fresh [Unreleased] above it. Pre-releases skip the roll so that
# [Unreleased] keeps collecting entries until the final version is stamped.
if [ -n "${prerelease}" ]; then
  echo "CHANGELOG.md: roll skipped for pre-release ${new}"
elif [ -f CHANGELOG.md ]; then
  if ! grep -q '^## \[Unreleased\]' CHANGELOG.md; then
    echo "warning: CHANGELOG.md has no [Unreleased] section, leaving it unchanged" >&2
  else
    body=$(awk '
      /^## \[Unreleased\]/ {inblk=1; next}
      inblk && /^## / {exit}
      inblk {print}
    ' CHANGELOG.md | grep -Ev '^[[:space:]]*$|^###' || true)
    if [ -z "${body}" ]; then
      echo "warning: no entries under [Unreleased] to release" >&2
    fi
    awk -v ver="${new}" -v date="${today}" '
      !done && /^## \[Unreleased\]/ {
        print "## [Unreleased]"
        print ""
        print "## [" ver "] - " date
        done=1
        next
      }
      { print }
    ' CHANGELOG.md > CHANGELOG.md.tmp && mv CHANGELOG.md.tmp CHANGELOG.md
    echo "CHANGELOG.md: released ${new} (${today})"
  fi
fi
