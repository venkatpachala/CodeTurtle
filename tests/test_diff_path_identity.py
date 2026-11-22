from core.change_units import build_change_units
from core.verification.diff_index import build_diff_index


DIFF='''diff --git a/auth/mod.rs b/auth/mod.rs
--- a/auth/mod.rs
+++ b/auth/mod.rs
@@ -40,1 +40,1 @@
-require_auth();
+allow_request();
diff --git a/cache/mod.rs b/cache/mod.rs
--- a/cache/mod.rs
+++ b/cache/mod.rs
@@ -90,1 +90,1 @@
-evict_old();
+retain_old();
'''


def test_exact_path_never_resolves_to_another_file_with_same_basename():
    index=build_diff_index(DIFF)
    assert index.hunks_for("auth/mod.rs")[0].new_start==40
    assert index.hunks_for("cache/mod.rs")[0].new_start==90
    units=build_change_units(DIFF,sorted(index.files),index=index)
    assert [(u.path,u.start_line) for u in units]==[("auth/mod.rs",40),("cache/mod.rs",90)]


def test_ambiguous_alias_or_wrong_directory_never_selects_arbitrary_hunks():
    index=build_diff_index(DIFF)
    assert index.hunks_for("mod.rs")==[]
    assert index.hunks_for("other/mod.rs")==[]
    assert index.hunks_for("C:/repo/auth/mod.rs")[0].file=="auth/mod.rs"
    assert index.hunks_for("AUTH/MOD.RS")[0].file=="auth/mod.rs"


def test_case_distinct_git_paths_keep_exact_identity_and_reject_folded_ambiguity():
    index=build_diff_index(DIFF.replace("cache/mod.rs","AUTH/mod.rs"))
    assert index.hunks_for("auth/mod.rs")[0].new_start==40
    assert index.hunks_for("AUTH/mod.rs")[0].new_start==90
    assert index.hunks_for("Auth/mod.rs")==[]
