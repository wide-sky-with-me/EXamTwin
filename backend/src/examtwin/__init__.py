"""ExamTwin multi-subject knowledge and assessment backend."""

import os

__version__ = "0.1.0"

# Model pricing metadata is not part of the answering path. Keep imports and
# ordinary tests deterministic instead of contacting GitHub during startup.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
