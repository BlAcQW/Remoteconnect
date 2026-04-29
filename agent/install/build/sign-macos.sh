#!/usr/bin/env bash
# Optionally sign + notarize a macOS app and pkg.
#
# Required env vars to actually sign:
#   APPLE_DEVELOPER_ID    "Developer ID Application: Hegnone Tech Ltd. (XXXXXXXX)"
#   APPLE_TEAM_ID         e.g. ABCD1234EF
#   APPLE_ID              your Apple developer account email
#   APPLE_NOTARIZE_PASSWORD  app-specific password (NOT your Apple ID password)
#
# No-op (warns + exits 0) if any of these are missing — build still works.
set -euo pipefail

APP="${1:-}"
PKG="${2:-}"

if [ -z "${APPLE_DEVELOPER_ID:-}" ]; then
  echo "→ skipping signing — set APPLE_DEVELOPER_ID, APPLE_TEAM_ID, APPLE_ID, APPLE_NOTARIZE_PASSWORD to enable"
  exit 0
fi

if [ -n "${APP}" ] && [ -d "${APP}" ]; then
  codesign --deep --force --options runtime \
           --sign "${APPLE_DEVELOPER_ID}" \
           "${APP}"
  echo "✓ signed app: ${APP}"

  # Notarize: zip → submit → wait → staple
  ZIP="${APP%.app}-notarize.zip"
  ditto -c -k --keepParent "${APP}" "${ZIP}"
  xcrun notarytool submit "${ZIP}" \
        --apple-id "${APPLE_ID}" \
        --team-id "${APPLE_TEAM_ID}" \
        --password "${APPLE_NOTARIZE_PASSWORD}" \
        --wait
  xcrun stapler staple "${APP}"
  rm -f "${ZIP}"
  echo "✓ notarized + stapled: ${APP}"
fi

if [ -n "${PKG}" ] && [ -f "${PKG}" ]; then
  productsign --sign "${APPLE_DEVELOPER_ID}" "${PKG}" "${PKG}.signed"
  mv "${PKG}.signed" "${PKG}"
  echo "✓ signed pkg: ${PKG}"
fi
