SHELL := /bin/bash
VENV := .venv

.PHONY: venv clean

venv: $(VENV)/.installed

$(VENV)/.installed: pyproject.toml
	@if command -v uv >/dev/null 2>&1; then \
		uv venv $(VENV) --python 3.13 && \
		uv pip install -e ".[test]"; \
	else \
		ml lang/Python/3.13.5-GCCcore-14.3.0 && \
		python3 -m venv $(VENV) && \
		$(VENV)/bin/pip install --upgrade pip && \
		$(VENV)/bin/pip install -e ".[test]"; \
	fi
	@touch $@

clean:
	@if command -v deactivate >/dev/null 2>&1; then \
		deactivate; \
	fi
	rm -rf $(VENV)
