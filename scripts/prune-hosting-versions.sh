#!/usr/bin/env bash
# Prune old Firebase Hosting versions, keeping the newest $KEEP per site.
# The live (released) version cannot be deleted; the API rejects it safely.
set -euo pipefail
PROJECT="studio-3654876024-6b075"
KEEP="${KEEP:-5}"
TOKEN=$(gcloud auth print-access-token)
api() {
  curl -s -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT" "$@"
}
for SITE in ayla-bot ayla-tantra studio-3654876024-6b075; do
  echo "== $SITE =="
  api "https://firebasehosting.googleapis.com/v1beta1/sites/$SITE/versions?pageSize=300" \
    | python3 -c "
import json,sys
d=json.load(sys.stdin)
vs=[v for v in d.get('versions',[]) if v.get('status')=='FINALIZED']
vs.sort(key=lambda v:v.get('createTime',''),reverse=True)
for v in vs[int('$KEEP'):]: print(v['name'])
" | while read -r NAME; do
      R=$(api -X DELETE "https://firebasehosting.googleapis.com/v1beta1/$NAME")
      if echo "$R" | grep -q '"error"'; then echo "skip (live): $NAME"; else echo "deleted: $NAME"; fi
    done
done
echo "done"
