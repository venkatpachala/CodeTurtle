"""
Fixture PR used as an OFFLINE fallback only (see DEFAULT_REPO/DEFAULT_PR below
for the default LIVE target every stage script now uses).

This is a real (small) diff with several deliberately planted issues so you have
ground truth to judge each agent's output against:

  1. Mutable default argument (`retries=[]`) — classic Python footgun.
  2. Off-by-one in the batch-slicing loop (`range(0, len(users), batch_size + 1)`).
  3. Bare `except:` that silently swallows send failures (no logging, no re-raise).
  4. `notified_count` is incremented even when `send_one` raises, so the returned
     count is wrong whenever anything fails.
  5. No rate limiting despite the PR description claiming "throttled batches".

Edit SAMPLE_PR below to test against your own local PR content — title/body/
files_changed/full_diff are exactly the fields `ReviewState` expects.
"""

# The real repo + PR every stage script defaults to. Already indexed into your
# Qdrant collection per your own `codeturtle add-repo NousResearch/hermes-agent`.
DEFAULT_REPO = "NousResearch/hermes-agent"
DEFAULT_PR = 64015

SAMPLE_PR = {
    "repo": "your-org/your-repo",          # used only by 03_test_evidence_retrieval.py
    "number": 101,
    "title": "Add throttled batch processing for user notifications",
    "body": (
        "This PR adds batch processing for the notification sender so we stop "
        "hitting the provider's rate limit. Notifications are now sent in "
        "batches of 50 with retry support. Should reduce our failure rate "
        "significantly during peak hours."
    ),
    "files_changed": ["notifications/batch.py"],
    "full_diff": '''diff --git a/notifications/batch.py b/notifications/batch.py
index 1a2b3c4..5d6e7f8 100644
--- a/notifications/batch.py
+++ b/notifications/batch.py
@@ -1,15 +1,38 @@
-def send_one(user, message):
-    provider.send(user.email, message)
+def send_one(user, message, retries=[]):
+    """Send a single notification, tracking retry attempts."""
+    try:
+        provider.send(user.email, message)
+        return True
+    except Exception:
+        retries.append(user.id)
+        return False
 
-def send_all(users, message):
-    for user in users:
-        send_one(user, message)
+def send_batch(users, message, batch_size=50):
+    """Send notifications in throttled batches of `batch_size`."""
+    notified_count = 0
+    for i in range(0, len(users), batch_size + 1):
+        batch = users[i:i + batch_size]
+        for user in batch:
+            send_one(user, message)
+            notified_count += 1
+    return notified_count
+
+def send_all(users, message):
+    return send_batch(users, message)
''',
}
