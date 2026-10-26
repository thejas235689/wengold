"""Machine learning over the graph — three methods, three jobs the exact code
cannot do on its own.

WENGOLD's kernel computes invalidation *exactly*: given a graph and a change it
says which results are invalidated, which still hold, and which are unknown. No
model is needed for that, and none is used for it. These three methods answer
questions the exact machinery does not:

* **unsupervised** (`unsupervised.py`) — cluster blocks by their dependency
  signature. The kernel treats every block as an individual; clustering finds the
  groups that share a signature, so one root cause covers a cluster and
  near-duplicate blocks surface as reuse candidates. Needs no labels, which is
  why it works on any project immediately.
* **supervised** (`supervised.py`) — predict whether a property will *fail*.
  The kernel cannot know that without running the check. The labels come from
  running the real formal engine, so the target is measured, not invented.
* **reinforcement** (`rl.py`) — learn the order to run checks in when the budget
  is limited. The kernel computes the minimum set but not the best order, and
  order matters as soon as you cannot afford all of it.

Every model here is plain Python: no numpy, no scikit-learn. The datasets are
small and the models are small, so a dependency would cost more than it earns.
What each method can and cannot support is stated where it is defined, and the
evaluations report held-out numbers rather than training numbers.
"""
from .features import (BLOCK_KEYS, RESULT_KEYS, block_features, dataset,  # noqa: F401
                       normalise, result_features, vector)

__all__ = ["BLOCK_KEYS", "RESULT_KEYS", "block_features", "result_features",
           "vector", "dataset", "normalise"]

# Waveform features: the same row format, read from a VCD instead of a graph.
# Graph features measured zero lift against simulation ground truth; a waveform is
# what the design actually did, cycle by cycle.
from .waveform_features import (FEATURE_KEYS as WAVE_FEATURE_KEYS,  # noqa: E402
                                activity_summary, signal_features,
                                waveform_dataset, waveform_features,
                                waveform_vector)

__all__ = list(globals().get("__all__", [])) + [
    "waveform_dataset", "waveform_features", "waveform_vector",
    "signal_features", "activity_summary", "WAVE_FEATURE_KEYS"]
