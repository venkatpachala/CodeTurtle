"""Deterministic risk signals are evidence leads, never mocked review results."""

from __future__ import annotations

from core.analysis.risk_signals import analyze_risk_signals, attach_signals_to_bundles
from core.agent.tools import BundleTools
from core.runtime.models import Bundle
from core.verification.diff_index import build_diff_index


def test_structural_contract_and_dataflow_signals(tmp_path):
    model = tmp_path / "app/models/optimized_image.rb"
    controller = tmp_path / "app/controllers/uploads_controller.rb"
    model.parent.mkdir(parents=True)
    controller.parent.mkdir(parents=True)
    model.write_text(
        """class OptimizedImage
  def self.resize_instructions_animated(from, to, dimensions, opts={})
    %W{ gifsicle --resize-fit #{dimensions} }
  end
  def self.downsize(from, to, max_width, max_height, opts={})
    optimize(from, to, \"#{max_width}x#{max_height}\", opts)
  end
  def self.downsize(from, to, dimensions, opts={})
    optimize(from, to, dimensions, opts)
  end
end
""",
        encoding="utf-8",
    )
    controller.write_text(
        """class UploadsController
  def create_upload
    while attempt > 0 && tempfile.size > limit
      OptimizedImage.downsize(tempfile.path, tempfile.path, \"80%\", allow_animation: enabled)
      attempt -= 1
    end
  end
end
""",
        encoding="utf-8",
    )
    diff = """diff --git a/app/controllers/uploads_controller.rb b/app/controllers/uploads_controller.rb
--- a/app/controllers/uploads_controller.rb
+++ b/app/controllers/uploads_controller.rb
@@ -1,1 +1,6 @@
+  while attempt > 0 && tempfile.size > limit
+    OptimizedImage.downsize(tempfile.path, tempfile.path, \"80%\", allow_animation: enabled)
+    attempt -= 1
diff --git a/app/models/optimized_image.rb b/app/models/optimized_image.rb
--- a/app/models/optimized_image.rb
+++ b/app/models/optimized_image.rb
@@ -1,1 +1,4 @@
+  def self.downsize(from, to, dimensions, opts={})
+    optimize(from, to, dimensions, opts)
+  end
"""
    files = ["app/controllers/uploads_controller.rb", "app/models/optimized_image.rb"]
    signals = analyze_risk_signals(repo_dir=tmp_path, files_changed=files, index=build_diff_index(diff))
    kinds = {signal.kind for signal in signals}
    assert {"duplicate_definition", "cross_file_argument_contract", "stale_loop_state"} <= kinds
    duplicate = next(signal for signal in signals if signal.kind == "duplicate_definition")
    assert duplicate.symbol == "self.downsize"
    assert len(duplicate.lines) == 2
    contract = next(signal for signal in signals if signal.kind == "cross_file_argument_contract")
    assert contract.symbol == "OptimizedImage.downsize"
    assert any("gifsicle --resize-fit" in item for item in contract.evidence)
    assert any("known_cli_contract" in item for item in contract.evidence)


def test_signals_are_scoped_to_the_bundle(tmp_path):
    path = tmp_path / "app/models/example.rb"
    path.parent.mkdir(parents=True)
    path.write_text("def self.x\nend\ndef self.x\nend\n", encoding="utf-8")
    diff = """diff --git a/app/models/example.rb b/app/models/example.rb
--- a/app/models/example.rb
+++ b/app/models/example.rb
@@ -1,1 +1,2 @@
+def self.x
+end
"""
    signals = analyze_risk_signals(
        repo_dir=tmp_path,
        files_changed=["app/models/example.rb"],
        index=build_diff_index(diff),
    )
    bundle = Bundle(id="B-001", paths=["app/models/example.rb"])
    attach_signals_to_bundles([bundle], signals)
    assert bundle.risk_signals
    assert bundle.risk_signals[0]["kind"] == "duplicate_definition"


def test_callee_contract_returns_bounded_dispatcher_evidence(tmp_path):
    source = tmp_path / "app/models/optimized_image.rb"
    source.parent.mkdir(parents=True)
    source.write_text(
        """class OptimizedImage
  def self.resize_instructions_animated(from, to, dimensions, opts={})
    %W{ gifsicle --resize-fit #{dimensions} }
  end
  def self.downsize(from, to, dimensions, opts={})
    optimize("downsize", from, to, dimensions, opts)
  end
  def self.optimize(operation, from, to, dimensions, opts={})
    method_name += "_animated" if opts[:allow_animation]
  end
end
""",
        encoding="utf-8",
    )
    tool = BundleTools(Bundle(id="B-001", paths=["app/controllers/uploads_controller.rb"]), repo_dir=tmp_path)
    result = tool.callee_contract("OptimizedImage.downsize")
    assert result["path"] == "app/models/optimized_image.rb"
    assert "def self.downsize" in result["text"]
    assert "allow_animation" in result["text"]
    assert "gifsicle --resize-fit" in result["text"]
